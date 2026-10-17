import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.rag.embeddings import get_embedder


@pytest.fixture
async def client(db, fake_embedder):
    """A signed-in owner: the session cookie from signup is kept by the client."""
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        signup = await c.post(
            "/auth/signup",
            json={"email": "owner@example.com", "password": "correct-horse", "name": "Owner"},
        )
        assert signup.status_code == 201
        yield c
    app.dependency_overrides.clear()


async def test_upload_document_is_ingested(client):
    business = (await client.post("/businesses", json={"name": "Salon"})).json()

    response = await client.post(
        f"/businesses/{business['id']}/documents",
        files={"file": ("info.md", b"# Parking\nFree parking for six cars.", "text/markdown")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "processing"

    # The background task has finished by the time the ASGI call returns.
    documents = (await client.get(f"/businesses/{business['id']}/documents")).json()
    assert documents[0]["status"] == "ready"

    results = (
        await client.post(f"/businesses/{business['id']}/search", json={"query": "parking"})
    ).json()
    assert "parking" in results[0]["content"].lower()


async def test_markdown_sent_as_octet_stream_is_accepted(client):
    business = (await client.post("/businesses", json={"name": "Salon"})).json()

    response = await client.post(
        f"/businesses/{business['id']}/documents",
        files={"file": ("faq.md", b"Hello", "application/octet-stream")},
    )
    assert response.status_code == 202


async def test_unsupported_file_type_is_rejected(client):
    business = (await client.post("/businesses", json={"name": "Salon"})).json()

    response = await client.post(
        f"/businesses/{business['id']}/documents",
        files={"file": ("photo.png", b"\x89PNG", "image/png")},
    )
    assert response.status_code == 415


async def test_unknown_business_returns_404(client):
    response = await client.get("/businesses/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_services_and_hours_crud(client):
    business = (await client.post("/businesses", json={"name": "Salon"})).json()
    base = f"/businesses/{business['id']}"
    assert business["timezone"] == "Asia/Kolkata"

    created = await client.post(
        f"{base}/services", json={"name": "Haircut", "duration_minutes": 30, "price": 500}
    )
    assert created.status_code == 201
    service_id = created.json()["id"]

    hours = {"days": [{"weekday": 1, "opens_at": "10:00", "closes_at": "18:00"}]}
    assert (await client.put(f"{base}/hours", json=hours)).status_code == 200
    assert (await client.get(f"{base}/hours")).json()[0]["opens_at"] == "10:00:00"

    deactivated = await client.patch(f"{base}/services/{service_id}", params={"active": False})
    assert deactivated.json()["active"] is False
    assert (await client.get(f"{base}/bookings")).json() == []


async def test_invalid_hours_are_rejected(client):
    business = (await client.post("/businesses", json={"name": "Salon"})).json()
    base = f"/businesses/{business['id']}"

    backwards = {"days": [{"weekday": 1, "opens_at": "18:00", "closes_at": "10:00"}]}
    duplicate = {
        "days": [
            {"weekday": 1, "opens_at": "10:00", "closes_at": "12:00"},
            {"weekday": 1, "opens_at": "13:00", "closes_at": "18:00"},
        ]
    }
    assert (await client.put(f"{base}/hours", json=backwards)).status_code == 422
    assert (await client.put(f"{base}/hours", json=duplicate)).status_code == 422


async def test_unknown_timezone_is_rejected(client):
    response = await client.post("/businesses", json={"name": "X", "timezone": "Mars/Base"})
    assert response.status_code == 422
