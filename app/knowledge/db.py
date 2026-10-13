"""Postgres-only setup for vector search. On SQLite both hooks do nothing."""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def before_create(conn: AsyncConnection) -> None:
    """Enable the pgvector extension (it must exist before a `vector(N)` column can be created)."""
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


async def after_create(conn: AsyncConnection) -> None:
    """Approximate-nearest-neighbour index for cosine search. Optional at demo scale, cheap to have."""
    if conn.dialect.name != "postgresql":
        return
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw "
            "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )
