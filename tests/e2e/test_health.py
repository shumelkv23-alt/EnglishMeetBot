"""E2E: HTTP-эндпоинты здоровья (нужен поднятый uvicorn + Postgres)."""
import pytest

pytestmark = pytest.mark.e2e


async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["message"] == "English Meet Bot is running"


async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
