from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./pylon_dummy.db"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    gmail_address: str = ""
    gmail_app_password: str = ""


settings = Settings()

#The settings loads all your config including secret from the .env file