# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    app_timezone: str = "Europe/Minsk"  # таймзона расписания и дедлайнов ежедневного опроса

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

    # LLM (OpenRouter)
    openrouter_api_key: str = ""  # ключ OpenRouter; пусто = генерация отключена (банк)
    llm_model: str = "deepseek/deepseek-chat"  # модель OpenRouter (можно free/дёшево)

    # LLM для игр (Anthropic Messages API — Azati)
    llm_api_key: str = ""  # x-api-key Azati; пусто = генерация отключена (банк слов)
    llm_base_url: str = "https://llm.azati.ai"  # база Anthropic Messages API
    llm_games_model: str = "Azati Fast"  # модель для генерации игрового контента

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.db_host}:{self.db_port}/{self.postgres_db}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()