import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.rag.embeddings import get_embedder


@pytest.fixture
async def client(db, fake_embedder):
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
