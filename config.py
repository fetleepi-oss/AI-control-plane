from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    database_url: str = "postgresql://controlplane:controlplane@localhost:5432/controlplane"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Provider credentials (server-side only, never exposed to clients)
    openrouter_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    class Config:
        env_file = ".env"


settings = Settings()
