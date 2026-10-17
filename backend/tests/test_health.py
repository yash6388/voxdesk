from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def test_health_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_services_health_reports_each_dependency(db, monkeypatch):
    # Point at ports where nothing listens, so the result doesn't depend on what's running.
    for field in ("mcp_url", "knowledge_agent_url", "booking_agent_url"):
        monkeypatch.setattr(get_settings(), field, "http://127.0.0.1:9")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/health/services")).json()

    statuses = {s["name"]: s["status"] for s in body["services"]}
    assert statuses == {
        "database": "up",
        "mcp_server": "down",
        "knowledge_agent": "down",
        "booking_agent": "down",
    }
    assert body["status"] == "degraded"
