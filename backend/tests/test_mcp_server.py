import json

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.fastmcp.exceptions import ToolError

from app.mcp import server
from tests.booking_fixtures import create_salon, next_weekday


@pytest.fixture
async def salon(db, monkeypatch):
    business, haircut = await create_salon()
    # In production the tenant comes from the X-Business-Id header; here we pin it.
    monkeypatch.setattr(server, "_business_id", lambda ctx: business.id)
    return business, haircut


async def call(name: str, **args):
    """Call a tool through FastMCP itself (schema validation + serialisation included)."""
    result = await server.mcp.call_tool(name, args)
    blocks = result[0] if isinstance(result, tuple) else result
    return [json.loads(b.text) for b in blocks]


async def test_tool_schemas_never_expose_business_id():
    for tool in await server.mcp.list_tools():
        assert "business_id" not in json.dumps(tool.inputSchema), tool.name
        assert "ctx" not in tool.inputSchema.get("properties", {}), tool.name


async def test_list_services_and_availability(salon):
    _, haircut = salon
    services = await call("list_services")
    assert services[0]["name"] == "Haircut"
    assert services[0]["price"] == "INR 500"

    day = next_weekday(1).isoformat()
    [availability] = await call("check_availability", service_id=str(haircut.id), date=day)
    assert availability["weekday"] == "Tuesday"
    assert availability["available_times"][0] == "10:00"


async def test_book_then_find_then_cancel(salon):
    _, haircut = salon
    day = next_weekday(1).isoformat()

    [booked] = await call(
        "book_appointment",
        service_id=str(haircut.id),
        date=day,
        time="11:00",
        customer_name="Asha",
        customer_phone="98765 43210",
    )
    assert booked["status"] == "confirmed" and booked["time"] == "11:00"
    assert booked["reference"] == booked["booking_id"].replace("-", "")[:6].upper()

    found = await call("find_my_bookings", customer_phone="9876543210")
    assert [b["booking_id"] for b in found] == [booked["booking_id"]]

    [cancelled] = await call(
        "cancel_booking", booking_id=booked["booking_id"], customer_phone="9876543210"
    )
    assert cancelled["status"] == "cancelled"


async def test_domain_errors_become_tool_errors(salon):
    _, haircut = salon
    with pytest.raises(ToolError, match="closed on Mondays"):
        await call(
            "book_appointment",
            service_id=str(haircut.id),
            date=next_weekday(0).isoformat(),
            time="11:00",
            customer_name="Asha",
            customer_phone="9876543210",
        )


async def test_bad_input_is_rejected(salon):
    with pytest.raises(ToolError, match="Invalid service id"):
        await call("check_availability", service_id="mens-haircut", date="2026-01-01")


async def test_requests_without_api_key_are_rejected():
    app = server.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/mcp", json={})
        wrong = await client.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert wrong.status_code == 401
