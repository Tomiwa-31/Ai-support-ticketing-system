from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.masking import Masker
from app.config import settings
from app.database import get_db
from app.knowledge import embeddings, store
from app.models import KnowledgeArticle, KnowledgeChunk

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class ArticleRead(BaseModel):
    id: int
    product: str
    title: str
    status: str
    source: str
    chunks: int


class HitRead(BaseModel):
    article_id: int
    chunk_id: int
    title: str
    score: float
    text: str


@router.get("/articles", response_model=list[ArticleRead])
async def list_articles(
    org_id: int = 1, product: str | None = None, status: str | None = None, db: AsyncSession = Depends(get_db)
):
    query = (
        select(KnowledgeArticle, func.count(KnowledgeChunk.id))
        .outerjoin(KnowledgeChunk, KnowledgeChunk.article_id == KnowledgeArticle.id)
        .where(KnowledgeArticle.org_id == org_id)
        .group_by(KnowledgeArticle.id)
        .order_by(KnowledgeArticle.id)
    )
    if product:
        query = query.where(KnowledgeArticle.product == product)
    if status:
        query = query.where(KnowledgeArticle.status == status)
    rows = (await db.execute(query)).all()
    return [
        ArticleRead(id=a.id, product=a.product, title=a.title, status=a.status, source=a.source, chunks=count)
        for a, count in rows
    ]


@router.get("/search", response_model=list[HitRead])
async def search_knowledge(q: str, product: str | None = None, org_id: int = 1, db: AsyncSession = Depends(get_db)):
    """Try the retrieval the AI uses: published articles only, filtered by organisation and product."""
    try:
        embedder = embeddings.get_embedder()
        result = await embedder.embed([Masker().mask(q)], input_type="query")
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    hits = await store.search(
        db, org_id=org_id, product=product, query_vector=result.vectors[0],
        embedding_model=result.model, k=settings.kb_top_k,
    )
    return [HitRead(article_id=h.article_id, chunk_id=h.chunk_id, title=h.title, score=round(h.score, 4), text=h.text) for h in hits]
