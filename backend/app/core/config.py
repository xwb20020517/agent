from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "car-manual-rag"
    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    STRICT_STARTUP_CHECK: bool = False
    AUTO_CREATE_TABLES: bool = True
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "123456"
    MYSQL_DATABASE: str = "car_manual_rag"
    MYSQL_ECHO: bool = False
    MYSQL_POOL_SIZE: int = 5
    MYSQL_MAX_OVERFLOW: int = 10

    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_SOCKET_TIMEOUT: float = 3.0

    JWT_SECRET_KEY: str = Field(default="please_change_me", min_length=8)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    LLM_PROVIDER: str = "dashscope"
    LLM_BASE_URL: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_API_KEY: str | None = None
    DASHSCOPE_API_KEY: str | None = None
    LLM_MODEL: str | None = "qwen3.6-flash-2026-04-16"
    LLM_ENABLE_THINKING: bool = True

    @computed_field
    @property
    def resolved_llm_api_key(self) -> str | None:
        return self.LLM_API_KEY or self.DASHSCOPE_API_KEY

    @computed_field
    @property
    def mysql_dsn(self) -> str:
        return (
            "mysql+asyncmy://"
            f"{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            "?charset=utf8mb4"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
