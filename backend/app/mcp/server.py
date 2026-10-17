"""VoxDesk MCP server: exposes booking operations as MCP tools.

Runs as its own service (Streamable HTTP on :8001), so ANY MCP client can use it —
our LangGraph agent, the MCP Inspector, Claude Desktop, Cursor…

    uv run python -m app.mcp.server

Every request must send:
    Authorization: Bearer <MCP_API_KEY>   → who may call the server at all
    X-Business-Id: <uuid>                 → which tenant the call is for
The tenant comes from the connection, never from tool arguments, so the LLM
cannot be talked into touching another business's bookings.
"""

import uuid
from datetime import date, datetime

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from starlette.responses import JSONResponse

from app.booking import service as booking
from app.booking.service import WEEKDAYS, BookingError
from app.config import get_settings
from app.db.models import Booking, Business, Service
from app.db.session import SessionLocal
from app.security import BearerKeyMiddleware

settings = get_settings()

mcp = FastMCP(
    "voxdesk",
    instructions=(
        "Booking tools for one business (selected by the X-Business-Id header). "
        "Call get_business_info first to learn today's date, timezone and opening hours. "
        "Dates are YYYY-MM-DD and times are 24h HH:MM in the business's local time."
    ),
    host=settings.mcp_host,
    port=settings.mcp_port,
    # Stateless: no server-side session between requests, so the server scales horizontally.
    stateless_http=True,
    json_response=True,
)


# ---------- Helpers ----------


def _business_id(ctx: Context) -> uuid.UUID:
    request = ctx.request_context.request
    raw = request.headers.get("x-business-id") if request else None
    try:
        return uuid.UUID(raw or "")
    except ValueError:
        raise ToolError("Missing or invalid X-Business-Id header.") from None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ToolError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from None


def _parse_datetime(day: str, hhmm: str) -> datetime:
    try:
        return datetime.fromisoformat(f"{_parse_date(day).isoformat()}T{hhmm}")
    except ValueError:
        raise ToolError(f"Invalid time '{hhmm}'. Use 24h HH:MM.") from None


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolError(f"Invalid {what} id.") from None


def _service_dict(s: Service, business: Business) -> dict:
    return {
        "service_id": str(s.id),
        "name": s.name,
        "duration_minutes": s.duration_minutes,
        "price": f"{business.currency} {s.price:,}" if s.price is not None else None,
        "description": s.description,
    }


def _booking_dict(b: Booking, business: Business) -> dict:
    start = booking.to_local(business, b.start_at)
    return {
        "booking_id": str(b.id),
        "service": b.service.name,
        "date": start.date().isoformat(),
        "time": start.strftime("%H:%M"),
        "when": start.strftime("%A %d %B, %I:%M %p"),
        "duration_minutes": b.service.duration_minutes,
        "customer_name": b.customer_name,
        "status": b.status.value,
    }


async def _run(fn):
    """Open a DB session and turn domain errors into MCP tool errors."""
    async with SessionLocal() as session:
        try:
            return await fn(session)
        except BookingError as exc:
            raise ToolError(str(exc)) from exc


# ---------- Tools ----------


@mcp.tool()
async def get_business_info(ctx: Context) -> dict:
    """Get the business's name, timezone, current local date/time and weekly opening hours.
    Call this first so you can resolve words like "tomorrow" or "Saturday" to dates."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        now = booking.business_now(business)
        hours = {h.weekday: h for h in await booking.get_hours(session, business.id)}
        return {
            "name": business.name,
            "timezone": business.timezone,
            "now": now.strftime("%Y-%m-%d %H:%M"),
            "today": f"{WEEKDAYS[now.weekday()]} {now.date().isoformat()}",
            "opening_hours": {
                day: (
                    f"{hours[i].opens_at:%H:%M}–{hours[i].closes_at:%H:%M}"
                    if i in hours
                    else "closed"
                )
                for i, day in enumerate(WEEKDAYS)
            },
        }

    return await _run(run)


@mcp.tool()
async def list_services(ctx: Context) -> list[dict]:
    """List bookable services with their service_id, duration and price."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        return [
            _service_dict(s, business) for s in await booking.list_services(session, business.id)
        ]

    return await _run(run)


@mcp.tool()
async def check_availability(service_id: str, date: str, ctx: Context) -> dict:
    """List free start times (HH:MM) for a service on a date (YYYY-MM-DD)."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        svc = await booking.get_service(session, business.id, _uuid(service_id, "service"))
        day = _parse_date(date)
        slots = await booking.available_slots(session, business, svc, day)
        return {
            "date": day.isoformat(),
            "weekday": WEEKDAYS[day.weekday()],
            "service": svc.name,
            "available_times": [s.strftime("%H:%M") for s in slots],
        }

    return await _run(run)


@mcp.tool()
async def book_appointment(
    service_id: str,
    date: str,
    time: str,
    customer_name: str,
    customer_phone: str,
    ctx: Context,
) -> dict:
    """Book a service at a date (YYYY-MM-DD) and start time (HH:MM) for a customer.
    Only call after the customer has chosen a time and given their name and phone."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        created = await booking.create_booking(
            session,
            business,
            _uuid(service_id, "service"),
            _parse_datetime(date, time),
            customer_name,
            customer_phone,
        )
        return _booking_dict(created, business)

    return await _run(run)


@mcp.tool()
async def find_my_bookings(customer_phone: str, ctx: Context) -> list[dict]:
    """Find a customer's upcoming confirmed bookings by phone number."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        found = await booking.find_bookings(session, business.id, customer_phone)
        return [_booking_dict(b, business) for b in found]

    return await _run(run)


@mcp.tool()
async def cancel_booking(booking_id: str, customer_phone: str, ctx: Context) -> dict:
    """Cancel a booking. The phone number must match the one used to book."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        cancelled = await booking.cancel_booking(
            session, business.id, _uuid(booking_id, "booking"), customer_phone
        )
        return _booking_dict(cancelled, business)

    return await _run(run)


@mcp.tool()
async def reschedule_booking(
    booking_id: str, customer_phone: str, new_date: str, new_time: str, ctx: Context
) -> dict:
    """Move a booking to a new date (YYYY-MM-DD) and time (HH:MM)."""

    async def run(session):
        business = await booking.get_business(session, _business_id(ctx))
        moved = await booking.reschedule_booking(
            session,
            business,
            _uuid(booking_id, "booking"),
            customer_phone,
            _parse_datetime(new_date, new_time),
        )
        return _booking_dict(moved, business)

    return await _run(run)


# ---------- HTTP app ----------


async def health(request):
    """Public liveness probe (used by the API's /health/services)."""
    return JSONResponse({"status": "ok"})


def create_app():
    app = mcp.streamable_http_app()
    app.add_route("/health", health, methods=["GET"])
    app.add_middleware(
        BearerKeyMiddleware, key=settings.mcp_api_key, public_paths=frozenset({"/health"})
    )
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host=settings.mcp_host, port=settings.mcp_port)
