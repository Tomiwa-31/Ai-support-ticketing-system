"""Load the demo knowledge articles (embeds them, so it needs VOYAGE_API_KEY). Safe to re-run: existing articles
are skipped.

    python -m app.knowledge.load_samples

Articles are loaded as `published` because the draft -> in_review -> published workflow arrives in Slice 5.
"""
import asyncio

from sqlalchemy import select

from app import models  # noqa: F401 -- registers models on Base.metadata
from app.database import AsyncSessionLocal, Base, engine
from app.knowledge import db as knowledge_db
from app.knowledge import embeddings, store
from app.knowledge.samples import SAMPLES, SOURCE
from app.models import KnowledgeArticle, Organization


async def load(embedder: embeddings.Embedder | None = None) -> tuple[int, int]:
    """Returns (added, skipped)."""
    async with engine.begin() as conn:
        await knowledge_db.before_create(conn)
        await conn.run_sync(Base.metadata.create_all)
        await knowledge_db.after_create(conn)

    async with AsyncSessionLocal() as session:
        org_id = await session.scalar(select(Organization.id).order_by(Organization.id).limit(1))
        if org_id is None:
            raise SystemExit("No organization found. Run `python seed.py` first.")
        existing = {
            (row.product, row.title)
            for row in (await session.execute(select(KnowledgeArticle.product, KnowledgeArticle.title).where(KnowledgeArticle.org_id == org_id))).all()
        }
        new = [s for s in SAMPLES if (s["product"], s["title"]) not in existing]
        if new:
            # One embedding request for all new articles, and wait-and-retry if Voyage rate-limits us (3 requests a
            # minute until a payment method is added to the Voyage account).
            embedder = embedder or embeddings.get_embedder(rate_limit_retries=4)
            await store.add_articles(session, new, org_id=org_id, status="published", source=SOURCE, embedder=embedder)
    return len(new), len(SAMPLES) - len(new)


async def main() -> None:
    try:
        added, skipped = await load()
    except embeddings.EmbeddingError as exc:
        raise SystemExit(f"Could not embed the articles: {exc}") from exc
    print(f"Knowledge articles: {added} added, {skipped} already present.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
