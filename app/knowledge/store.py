"""Knowledge store: add articles (chunk -> mask -> embed -> save) and search them.

Every search is filtered by organisation and product, returns published articles only, and only compares vectors made
by the same embedding model. Text is masked before it is embedded.
"""
import math
from dataclasses import dataclass

from sqlalchemy import Float, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.masking import Masker
from app.core.clock import utcnow
from app.knowledge import embeddings
from app.knowledge.chunking import chunk_article
from app.models.knowledge import ALL_PRODUCTS, ARTICLE_STATUSES, KnowledgeArticle, KnowledgeChunk


@dataclass
class Hit:
    chunk_id: int
    article_id: int
    title: str
    text: str
    score: float  # cosine similarity, higher is closer


async def add_articles(
    session: AsyncSession,
    items: list[dict],
    *,
    org_id: int,
    status: str = "draft",
    source: str = "product-docs",
    embedder: embeddings.Embedder | None = None,
) -> list[KnowledgeArticle]:
    """Add several articles with ONE embedding request (each item: product, title, body). Chunks are masked first."""
    if status not in ARTICLE_STATUSES:
        raise ValueError(f"unknown article status {status!r}")
    embedder = embedder or embeddings.get_embedder()
    masker = Masker()
    chunked = [chunk_article(item["title"], item["body"]) for item in items]
    texts = [masker.mask(chunk) for chunks in chunked for chunk in chunks]
    result = await embedder.embed(texts, input_type="document") if texts else None

    articles: list[KnowledgeArticle] = []
    cursor = 0
    for item, chunks in zip(items, chunked, strict=True):
        article = KnowledgeArticle(
            org_id=org_id, product=item["product"], title=item["title"], body=item["body"], status=status,
            source=source, published_at=utcnow() if status == "published" else None,
        )
        session.add(article)
        await session.flush()
        for index, chunk in enumerate(chunks):
            session.add(
                KnowledgeChunk(
                    article_id=article.id, org_id=org_id, product=item["product"], chunk_index=index,
                    text=chunk, embedding=result.vectors[cursor], embedding_model=result.model,
                )
            )
            cursor += 1
        articles.append(article)
    await session.commit()
    return articles


async def add_article(
    session: AsyncSession,
    *,
    org_id: int,
    product: str,
    title: str,
    body: str,
    status: str = "draft",
    source: str = "product-docs",
    embedder: embeddings.Embedder | None = None,
) -> KnowledgeArticle:
    (article,) = await add_articles(
        session, [{"product": product, "title": title, "body": body}],
        org_id=org_id, status=status, source=source, embedder=embedder,
    )
    return article


def _filters(org_id: int, product: str | None, embedding_model: str) -> list:
    products = [product, ALL_PRODUCTS] if product else [ALL_PRODUCTS]
    return [
        KnowledgeChunk.org_id == org_id,
        KnowledgeChunk.product.in_(products),
        KnowledgeArticle.status == "published",
        KnowledgeChunk.embedding_model == embedding_model,
        KnowledgeChunk.embedding.is_not(None),
    ]


def build_pg_search(org_id: int, product: str | None, query_vector: list[float], embedding_model: str, k: int) -> Select:
    """The Postgres query: pgvector's cosine distance operator does the ranking inside the database."""
    distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(query_vector)
    return (
        select(
            KnowledgeChunk.id, KnowledgeArticle.id, KnowledgeArticle.title, KnowledgeChunk.text,
            (1 - distance).label("score"),
        )
        .join(KnowledgeArticle, KnowledgeArticle.id == KnowledgeChunk.article_id)
        .where(*_filters(org_id, product, embedding_model))
        .order_by(distance)
        .limit(k)
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def search(
    session: AsyncSession,
    *,
    org_id: int,
    product: str | None,
    query_vector: list[float],
    embedding_model: str,
    k: int = 4,
) -> list[Hit]:
    if session.get_bind().dialect.name == "postgresql":
        rows = (await session.execute(build_pg_search(org_id, product, query_vector, embedding_model, k))).all()
        return [Hit(chunk_id=r[0], article_id=r[1], title=r[2], text=r[3], score=float(r[4])) for r in rows]

    # SQLite (local dev and tests): the same filters in SQL, ranking in Python.
    rows = (
        await session.execute(
            select(
                KnowledgeChunk.id, KnowledgeArticle.id, KnowledgeArticle.title, KnowledgeChunk.text,
                KnowledgeChunk.embedding,
            )
            .join(KnowledgeArticle, KnowledgeArticle.id == KnowledgeChunk.article_id)
            .where(*_filters(org_id, product, embedding_model))
        )
    ).all()
    hits = [Hit(chunk_id=r[0], article_id=r[1], title=r[2], text=r[3], score=_cosine(query_vector, r[4])) for r in rows]
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
