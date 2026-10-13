"""A column type for embeddings: a real pgvector `vector(N)` on Postgres, a JSON string on SQLite.

SQLite has no vector support, so local development and the test suite store the numbers as JSON text and rank in
Python (see store.search); on Postgres the database ranks with pgvector's cosine-distance operator.
"""
import json

from sqlalchemy import Text, cast, type_coerce
from sqlalchemy.types import TypeDecorator, UserDefinedType

EMBEDDING_DIM = 1024  # voyage-4 / voyage-finance-2 default output size; changing it needs a schema change


class PGVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dim})"

    def bind_expression(self, bindvalue):
        # Send the vector as text and cast it in SQL, so no driver-side codec is needed.
        return cast(cast(bindvalue, Text), self)


class Embedding(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(Text())

    def column_expression(self, col):
        # Read the vector back as text (no driver codec needed) but keep this type, so it is parsed into a list.
        return type_coerce(cast(col, Text), self)

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)  # pgvector's text form "[0.1,0.2]" is valid JSON
