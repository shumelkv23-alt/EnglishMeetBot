# app/main.py
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import get_settings
from app.api.health import router as health_router
from app.api.google_chat import router as google_chat_router

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
    from app.services.reminders import restore_reminders_on_startup
    from app.services.briefing import restore_briefings_on_startup

    await restore_reminders_on_startup()
    await restore_briefings_on_startup()
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

@app.get("/")
async def root():
    return {"message": "English Meet Bot is running"}