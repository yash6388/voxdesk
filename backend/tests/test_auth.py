from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import ALGORITHM, COOKIE_NAME
from app.config import get_settings
from app.db.models import Business
from app.db.session import SessionLocal
from app.main import app


def new_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def signup(client: AsyncClient, email: str, password: str = "correct-horse") -> dict:
    response = await client.post(
        "/auth/signup", json={"email": email, "password": password, "name": email.split("@")[0]}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_signup_sets_an_httponly_session_cookie(db):
    async with new_client() as client:
        response = await client.post(
            "/auth/signup",
            json={"email": "Asha@Example.com", "password": "correct-horse", "name": "Asha"},
        )
        cookie = response.headers["set-cookie"]
        assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
        assert response.json()["user"]["email"] == "asha@example.com"  # normalised

        me = await client.get("/auth/me")  # cookie sent automatically
        assert me.status_code == 200 and me.json()["name"] == "Asha"


async def test_duplicate_email_and_weak_password_are_rejected(db):
    async with new_client() as client:
        await signup(client, "a@example.com")
        dup = await client.post(
            "/auth/signup", json={"email": "A@example.com", "password": "another-pass", "name": "x"}
        )
        weak = await client.post(
            "/auth/signup", json={"email": "b@example.com", "password": "short", "name": "x"}
        )
    assert dup.status_code == 409
    assert weak.status_code == 422


async def test_login_logout_and_wrong_password(db):
    async with new_client() as client:
        await signup(client, "a@example.com")
        await client.post("/auth/logout")
        assert (await client.get("/auth/me")).status_code == 401

        wrong = await client.post(
            "/auth/login", json={"email": "a@example.com", "password": "nope-nope"}
        )
        unknown = await client.post(
            "/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"}
        )
        # Same message either way: no hint about which emails have accounts.
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

        ok = await client.post(
            "/auth/login", json={"email": "a@example.com", "password": "correct-horse"}
        )
        assert ok.status_code == 200
        assert (await client.get("/auth/me")).status_code == 200


async def test_bearer_token_works_without_cookies(db):
    async with new_client() as client:
        token = (await signup(client, "a@example.com"))["access_token"]
    async with new_client() as api_client:
        me = await api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


@pytest.mark.parametrize("kind", ["expired", "forged"])
async def test_expired_or_forged_tokens_are_rejected(db, kind):
    async with new_client() as client:
        user_id = (await signup(client, "a@example.com"))["user"]["id"]
    now = datetime.now(UTC)
    if kind == "expired":
        token = jwt.encode(
            {"sub": user_id, "exp": now - timedelta(minutes=1)},
            get_settings().jwt_secret,
            algorithm=ALGORITHM,
        )
    else:
        token = jwt.encode(
            {"sub": user_id, "exp": now + timedelta(days=1)},
            "an-attacker-controlled-secret-of-32-bytes!",
        )
    async with new_client() as client:
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401


async def test_management_endpoints_require_login(db):
    async with new_client() as client:
        assert (await client.get("/businesses")).status_code == 401
        assert (await client.post("/businesses", json={"name": "X"})).status_code == 401


async def test_owners_cannot_see_or_touch_each_others_businesses(db):
    async with new_client() as alice, new_client() as bob:
        await signup(alice, "alice@example.com")
        await signup(bob, "bob@example.com")
        salon = (await alice.post("/businesses", json={"name": "Alice Salon"})).json()
        base = f"/businesses/{salon['id']}"

        assert [b["name"] for b in (await bob.get("/businesses")).json()] == []
        # 404, not 403: Bob can't even learn the business exists.
        for method, path in [
            ("get", base),
            ("delete", base),
            ("get", f"{base}/documents"),
            ("get", f"{base}/services"),
            ("get", f"{base}/bookings"),
            ("put", f"{base}/hours"),
        ]:
            kwargs = {"json": {"days": []}} if method == "put" else {}
            response = await getattr(bob, method)(path, **kwargs)
            assert response.status_code == 404, (method, path, response.status_code)

        # Alice still has full access.
        assert (await alice.get(f"{base}/services")).status_code == 200


async def test_first_signup_claims_businesses_created_before_accounts_existed(db):
    async with SessionLocal() as session:
        session.add(Business(name="Legacy Salon"))
        await session.commit()
    async with new_client() as first, new_client() as second:
        await signup(first, "first@example.com")
        await signup(second, "second@example.com")
        assert [b["name"] for b in (await first.get("/businesses")).json()] == ["Legacy Salon"]
        assert (await second.get("/businesses")).json() == []


async def test_public_business_page_by_slug_exposes_only_public_fields(db):
    async with new_client() as owner:
        await signup(owner, "owner@example.com")
        first = (await owner.post("/businesses", json={"name": "Glow Studio!"})).json()
        second = (await owner.post("/businesses", json={"name": "Glow Studio"})).json()
    assert first["slug"] == "glow-studio"
    assert second["slug"].startswith("glow-studio-") and second["slug"] != first["slug"]

    async with new_client() as anonymous:
        page = await anonymous.get(f"/public/businesses/{first['slug']}")
        missing = await anonymous.get("/public/businesses/does-not-exist")
    assert page.status_code == 200
    assert set(page.json()) == {"id", "slug", "name", "description"}
    assert missing.status_code == 404


def test_production_refuses_development_secrets():
    from app.config import Settings

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="production").check_production_safety()
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        Settings(
            _env_file=None, environment="production", jwt_secret="x" * 40
        ).check_production_safety()
    Settings(  # a properly configured production setup passes
        _env_file=None, environment="production", jwt_secret="x" * 40, cookie_secure=True
    ).check_production_safety()
