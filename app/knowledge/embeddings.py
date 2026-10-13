"""The embedding seam. Callers talk to `Embedder`; only VoyageEmbedder knows Voyage's REST API. Mask text BEFORE
calling this: nothing here inspects or redacts what it is given."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx2

from app.config import settings
from app.knowledge.vector import EMBEDDING_DIM

logger = logging.getLogger(__name__)

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
BATCH_SIZE = 64
RATE_LIMIT_WAIT_SECONDS = 21.0  # a 3-requests-per-minute limit (Voyage's no-payment-method tier) frees up after ~20 s
InputType = Literal["document", "query"]


class EmbeddingError(Exception):
    """Embedding failed or returned something unusable. The message is safe to store and show."""


@dataclass
class EmbedResult:
    vectors: list[list[float]]
    model: str
    total_tokens: int


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str], *, input_type: InputType) -> EmbedResult: ...


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str, rate_limit_retries: int = 0) -> None:
        self.model = model
        self._api_key = api_key
        # 0 for live traffic (a slow embedding call must not stall a ticket: the AI worker degrades instead);
        # the one-off article loader waits and retries.
        self._rate_limit_retries = rate_limit_retries

    async def embed(self, texts: list[str], *, input_type: InputType) -> EmbedResult:
        vectors: list[list[float]] = []
        tokens = 0
        async with httpx2.AsyncClient(timeout=30.0) as client:
            for start in range(0, len(texts), BATCH_SIZE):
                batch = texts[start : start + BATCH_SIZE]
                for attempt in range(self._rate_limit_retries + 1):
                    try:
                        response = await client.post(
                            VOYAGE_URL,
                            headers={"Authorization": f"Bearer {self._api_key}"},
                            json={"input": batch, "model": self.model, "input_type": input_type},
                        )
                    except Exception as exc:  # noqa: BLE001 -- network failure: report the type only, never the payload
                        raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
                    if response.status_code == 429 and attempt < self._rate_limit_retries:
                        wait = _retry_after(response)
                        logger.warning("embedding rate limited; waiting %.0f s (retry %d)", wait, attempt + 1)
                        await asyncio.sleep(wait)
                        continue
                    break
                if response.status_code != 200:
                    raise EmbeddingError(f"embedding API returned {response.status_code}: {response.text[:200]}")
                body = response.json()
                rows = sorted(body["data"], key=lambda row: row["index"])
                if len(rows) != len(batch):
                    raise EmbeddingError("embedding API returned the wrong number of vectors")
                vectors.extend(row["embedding"] for row in rows)
                tokens += int(body.get("usage", {}).get("total_tokens", 0))
        if any(len(v) != EMBEDDING_DIM for v in vectors):
            raise EmbeddingError(f"embedding size is not {EMBEDDING_DIM}; the vector column is fixed at that size")
        return EmbedResult(vectors=vectors, model=self.model, total_tokens=tokens)


def _retry_after(response) -> float:
    try:
        return max(1.0, float(response.headers.get("retry-after", RATE_LIMIT_WAIT_SECONDS)))
    except ValueError:
        return RATE_LIMIT_WAIT_SECONDS


_override: Embedder | None = None


def set_embedder(embedder: Embedder | None) -> None:
    """Swap the embedder (tests use a fake). Pass None to restore the real one."""
    global _override
    _override = embedder


def get_embedder(rate_limit_retries: int = 0) -> Embedder:
    if _override is not None:
        return _override
    if not settings.voyage_api_key:
        raise EmbeddingError("VOYAGE_API_KEY is not set")
    return VoyageEmbedder(settings.voyage_api_key, settings.embedding_model, rate_limit_retries)
