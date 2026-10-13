from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.database import Base
from app.knowledge.vector import Embedding

# KnowledgeArticle.status: draft -> in_review -> published. Only published articles are ever retrieved.
# (The review workflow itself arrives in Slice 5; Slice 2 loads curated sample articles as published.)
ARTICLE_STATUSES = ("draft", "in_review", "published")
ALL_PRODUCTS = "all"  # an article that applies to every product


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    product: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String, nullable=False, default="product-docs")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeChunk(Base):
    """A slice of an article with its embedding. The embedding model is stored with every vector so vectors from
    different models (which are not comparable) are never mixed."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("knowledge_articles.id"), nullable=False)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    product: Mapped[str] = mapped_column(String, nullable=False)  # copied from the article so a search filters in one table
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding(), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
