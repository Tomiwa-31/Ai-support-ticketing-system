from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _async_database_url(url: str) -> str:
    """Accept a provider-style Postgres URL (e.g. Neon's) and make it work with SQLAlchemy + asyncpg."""
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
        return url
    query = dict(parse_qsl(parts.query))
    if "sslmode" in query:
        query["ssl"] = query.pop("sslmode")  # asyncpg spells it `ssl`
    query.pop("channel_binding", None)  # not understood by asyncpg
    return urlunsplit(parts._replace(scheme="postgresql+asyncpg", query=urlencode(query)))


# pool_pre_ping: hosted Postgres (e.g. Neon) closes idle connections, so test one before reusing it.
engine = create_async_engine(_async_database_url(settings.database_url), echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

#sqlite+aiosqlite:///./pylon_dummy.db
#sqlite: which database type
#aiosqlite: the async driver
#///: separator
#./pylon_dummy.db: file path, where ./ means "the folder you ran uvicorn from"

#get_db()

#It doesn't run everything. It only manages the session's lifetime for one request:

#A request comes in, so it opens a session.
#yield hands the session to your endpoint, which does its work.
#When the endpoint finishes, it resumes and closes the session.