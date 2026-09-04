# app/main.py
import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.api.health import router as health_router
from app.api.google_chat import router as google_chat_router

# Windows: stdout/stderr по умолчанию в cp1251, а в логах встречаются эмодзи —
# без этого каждый такой лог валится с UnicodeEncodeError и засоряет err-лог.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

settings = get_settings()

# Настройка логирования
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.scheduler import init_scheduler, shutdown_scheduler

    logger.info(f"Starting up application in {settings.app_env} mode...")
    await init_scheduler()
    from app.cards.seed import ensure_seeded
    from app.services.reminders import restore_reminders_on_startup
    from app.cards.service import restore_cards_on_startup

    # Идемпотентный сид каталога карточек + контент-банка (на чистой БД иначе пусто).
    await ensure_seeded()
    await restore_reminders_on_startup()
    await restore_cards_on_startup()
    yield
    shutdown_scheduler()
    logger.info("Shutting down application...")

# ВАЖНО: переменная должна называться именно app
app = FastAPI(
    title="English Meet Bot API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router, prefix="/api/v1", tags=["Health"])
app.include_router(google_chat_router)

# Отдача сгенерированных изображений игр (например, сетка кроссворда) через /static.
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(os.path.join(_STATIC_DIR, "crosswords"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/")
async def root():
    return {"message": "English Meet Bot is running"}