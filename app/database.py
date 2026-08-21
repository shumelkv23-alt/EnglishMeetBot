# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

# Создаем асинхронный движок
engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),  # Показывает SQL-запросы в консоли в режиме разработки
    pool_pre_ping=True,                        # Проверяет соединение перед использованием
)

# Создаем фабрику сессий
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Базовый класс для всех ORM-моделей
class Base(DeclarativeBase):
    pass

# Зависимость для получения сессии БД в эндпоинтах FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session