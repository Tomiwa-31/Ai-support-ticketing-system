from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./pylon_dummy.db"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    gmail_address: str = ""
    gmail_app_password: str = ""

    # v2 AI layer. Blank key = the AI worker records failed runs instead of calling the model.
    anthropic_api_key: str = ""
    # Only needed when the API key is not scoped to a single workspace (the API then demands this id).
    anthropic_workspace_id: str = ""
    ai_model: str = "claude-haiku-5-5"
    ai_max_output_tokens: int = 8000

    # Tool gateway (MCP). Each AI run may make at most this many tool calls; each call has this timeout.
    ai_max_tool_calls: int = 4
    ai_tool_timeout_seconds: float = 15.0

    # Knowledge base (RAG). Voyage AI makes the embeddings; blank key = retrieval is skipped and logged as failed.
    voyage_api_key: str = ""
    embedding_model: str = "voyage-4"  # 1024 dimensions; the vector column is fixed at that size
    kb_top_k: int = 4
    # Hits scoring below this (cosine similarity) are not shown to the model. Calibrated on voyage-4 with the demo articles:
    # real matches scored 0.57-0.68, weak neighbours 0.2-0.5, off-topic text <= 0.12. Re-check if the model or corpus changes.
    kb_min_score: float = 0.3


settings = Settings()

#The settings loads all your config including secret from the .env file