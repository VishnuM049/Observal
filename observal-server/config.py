from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/observal"
    CLICKHOUSE_URL: str = "clickhouse://localhost:8123/observal"
    SECRET_KEY: str = "change-me-in-production"
    API_KEY_LENGTH: int = 32

    model_config = {"env_file": ".env"}


settings = Settings()
