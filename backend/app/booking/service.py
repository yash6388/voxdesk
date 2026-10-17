"""Booking domain logic, shared by the owner REST API and the MCP server.

All times are timezone-aware. Callers pass local times in the business's timezone;
the database stores UTC (timestamptz).
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Booking, BookingStatus, Business, BusinessHours, Service

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class BookingError(Exception):
    """A rule was broken. The message is safe to show to the customer."""


def normalize_phone(phone: str) -> str:
    """Keep digits (and a leading +) so '98765 43210' and '9876543210' match."""
    phone = phone.strip()
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        raise BookingError("Please provide a valid phone number.")
    return ("+" if phone.startswith("+") else "") + digits


def business_now(business: Business) -> datetime:
    return datetime.now(ZoneInfo(business.timezone))


def to_local(business: Business, value: datetime) -> datetime:
    """Interpret naive datetimes as business-local time; convert aware ones to it."""
    tz = ZoneInfo(business.timezone)
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


# ---------- Reads ----------


async def get_business(session: AsyncSession, business_id: uuid.UUID) -> Business:
    business = await session.get(Business, business_id)
    if business is None:
        raise BookingError("Business not found.")
    return business


async def list_services(
    session: AsyncSession, business_id: uuid.UUID, include_inactive: bool = False
) -> list[Service]:
    query = select(Service).where(Service.business_id == business_id).order_by(Service.name)
    if not include_inactive:
        query = query.where(Service.active)
    return list(await session.scalars(query))


async def get_service(
    session: AsyncSession, business_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    service = await session.get(Service, service_id)
    if service is None or service.business_id != business_id or not service.active:
        raise BookingError("That service isn't available.")
    return service


async def get_hours(session: AsyncSession, business_id: uuid.UUID) -> list[BusinessHours]:
    return list(
        await session.scalars(
            select(BusinessHours)
            .where(BusinessHours.business_id == business_id)
            .order_by(BusinessHours.weekday)
        )
    )


async def _busy_intervals(
    session: AsyncSession,
    business_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exclude_booking: uuid.UUID | None = None,
) -> list[tuple[datetime, datetime]]:
    query = select(Booking.start_at, Booking.end_at).where(
        Booking.business_id == business_id,
        Booking.status == BookingStatus.CONFIRMED,
        Booking.start_at < end,
        Booking.end_at > start,
    )
    if exclude_booking:
        query = query.where(Booking.id != exclude_booking)
    return [(row.start_at, row.end_at) for row in await session.execute(query)]


def _opening_window(
    business: Business, hours: list[BusinessHours], day: date
) -> tuple[datetime, datetime] | None:
    tz = ZoneInfo(business.timezone)
    for h in hours:
        if h.weekday == day.weekday():
            return datetime.combine(day, h.opens_at, tz), datetime.combine(day, h.closes_at, tz)
    return None


async def available_slots(
    session: AsyncSession, business: Business, service: Service, day: date
) -> list[datetime]:
    """Start times on `day` where the service fits inside opening hours without
    overlapping a confirmed booking, and that aren't in the past."""
    settings = get_settings()
    now = business_now(business)
    if day < now.date() or day > now.date() + timedelta(days=settings.booking_horizon_days):
        return []

    window = _opening_window(business, await get_hours(session, business.id), day)
    if window is None:
        return []
    opens, closes = window
    duration = timedelta(minutes=service.duration_minutes)
    busy = await _busy_intervals(session, business.id, opens, closes)

    slots, step = [], timedelta(minutes=settings.slot_step_minutes)
    start = opens
    while start + duration <= closes:
        end = start + duration
        if start > now and all(not (start < b_end and end > b_start) for b_start, b_end in busy):
            slots.append(start)
        start += step
    return slots


async def find_bookings(
    session: AsyncSession, business_id: uuid.UUID, phone: str, upcoming_only: bool = True
) -> list[Booking]:
    query = (
        select(Booking)
        .options(selectinload(Booking.service))
        .where(Booking.business_id == business_id, Booking.customer_phone == normalize_phone(phone))
        .order_by(Booking.start_at)
    )
    if upcoming_only:
        query = query.where(
            Booking.status == BookingStatus.CONFIRMED, Booking.end_at > datetime.now().astimezone()
        )
    return list(await session.scalars(query))


async def list_bookings(session: AsyncSession, business_id: uuid.UUID) -> list[Booking]:
    return list(
        await session.scalars(
            select(Booking)
            .options(selectinload(Booking.service))
            .where(Booking.business_id == business_id)
            .order_by(Booking.start_at.desc())
        )
    )


# ---------- Writes ----------


async def _validate_slot(
    session: AsyncSession,
    business: Business,
    service: Service,
    start: datetime,
    exclude_booking: uuid.UUID | None = None,
) -> tuple[datetime, datetime]:
    start = to_local(business, start)
    end = start + timedelta(minutes=service.duration_minutes)
    if start <= business_now(business):
        raise BookingError("That time is in the past.")

    window = _opening_window(business, await get_hours(session, business.id), start.date())
    if window is None:
        raise BookingError(f"We're closed on {WEEKDAYS[start.weekday()]}s.")
    opens, closes = window
    if start < opens or end > closes:
        raise BookingError(
            f"That doesn't fit our hours ({opens:%H:%M}–{closes:%H:%M}) for a "
            f"{service.duration_minutes}-minute {service.name}."
        )
    if await _busy_intervals(session, business.id, start, end, exclude_booking):
        raise BookingError("Sorry, that time is already booked.")
    return start, end


async def _commit_or_conflict(session: AsyncSession) -> None:
    """The exclusion constraint is the final guard against concurrent double-booking."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "ex_bookings_no_overlap" in str(exc.orig):
            raise BookingError("Sorry, that time was just booked by someone else.") from exc
        raise


async def create_booking(
    session: AsyncSession,
    business: Business,
    service_id: uuid.UUID,
    start: datetime,
    customer_name: str,
    customer_phone: str,
) -> Booking:
    if not customer_name.strip():
        raise BookingError("Please provide the customer's name.")
    service = await get_service(session, business.id, service_id)
    start, end = await _validate_slot(session, business, service, start)

    booking = Booking(
        business_id=business.id,
        service_id=service.id,
        customer_name=customer_name.strip(),
        customer_phone=normalize_phone(customer_phone),
        start_at=start,
        end_at=end,
    )
    session.add(booking)
    await _commit_or_conflict(session)
    booking.service = service
    return booking


async def _get_customer_booking(
    session: AsyncSession, business_id: uuid.UUID, booking_id: uuid.UUID, phone: str
) -> Booking:
    booking = await session.get(Booking, booking_id, options=[selectinload(Booking.service)])
    # Phone acts as a lightweight ownership check: you can only change your own booking.
    if (
        booking is None
        or booking.business_id != business_id
        or booking.customer_phone != normalize_phone(phone)
    ):
        raise BookingError("I couldn't find that booking for this phone number.")
    if booking.status != BookingStatus.CONFIRMED:
        raise BookingError("That booking is already cancelled.")
    return booking


async def cancel_booking(
    session: AsyncSession, business_id: uuid.UUID, booking_id: uuid.UUID, phone: str
) -> Booking:
    booking = await _get_customer_booking(session, business_id, booking_id, phone)
    booking.status = BookingStatus.CANCELLED
    await session.commit()
    return booking


async def reschedule_booking(
    session: AsyncSession,
    business: Business,
    booking_id: uuid.UUID,
    phone: str,
    new_start: datetime,
) -> Booking:
    booking = await _get_customer_booking(session, business.id, booking_id, phone)
    start, end = await _validate_slot(
        session, business, booking.service, new_start, exclude_booking=booking.id
    )
    booking.start_at, booking.end_at = start, end
    await _commit_or_conflict(session)
    return booking


async def set_hours(
    session: AsyncSession, business_id: uuid.UUID, week: list[tuple[int, time, time]]
) -> list[BusinessHours]:
    """Replace the whole week's opening hours (days not listed are closed)."""
    for row in await get_hours(session, business_id):
        await session.delete(row)
    await session.flush()
    session.add_all(
        BusinessHours(business_id=business_id, weekday=d, opens_at=o, closes_at=c)
        for d, o, c in week
    )
    await session.commit()
    return await get_hours(session, business_id)
