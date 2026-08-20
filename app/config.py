# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    
    # DB settings
    postgres_user: str
    postgres_password: str
    postgres_db: str
    db_host: str = "localhost"
    db_port: int = 5432

    # Google Chat
    chat_app_audience: str = ""        # Audience из "Authentication audience" в Chat App Configuration (обычно URL endpoint'а)
    skip_jwt_validation: bool = False  # true только для локальных тестов без реального Google
    google_sa_key_file: str = "sa-key.json"  # ключ сервисного аккаунта (app-auth, chat.bot)
    chat_test_space: str = ""          # space для ручных проверок проактивной отправки

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.db_host}:{self.db_port}/{self.postgres_db}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()