import asyncio

import pytest

from app.booking import service as booking
from app.booking.service import BookingError
from app.db.models import BookingStatus
from app.db.session import SessionLocal
from tests.booking_fixtures import at, create_salon, next_weekday

TUESDAY, MONDAY = 1, 0


async def book(business, service, start, phone="9876543210", name="Asha"):
    async with SessionLocal() as session:
        return await booking.create_booking(session, business, service.id, start, name, phone)


async def test_slots_fit_inside_opening_hours(db):
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)

    async with SessionLocal() as session:
        slots = await booking.available_slots(session, business, haircut, day)

    times = [s.strftime("%H:%M") for s in slots]
    assert times[0] == "10:00"
    assert times[-1] == "17:30"  # a 30-min service must finish by 18:00
    assert len(times) == 16


async def test_no_slots_on_closed_day(db):
    business, haircut = await create_salon()
    async with SessionLocal() as session:
        assert await booking.available_slots(session, business, haircut, next_weekday(MONDAY)) == []


async def test_booked_slot_disappears_from_availability(db):
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)
    await book(business, haircut, at(day, "11:00"))

    async with SessionLocal() as session:
        times = [
            s.strftime("%H:%M")
            for s in await booking.available_slots(session, business, haircut, day)
        ]
    assert "11:00" not in times
    assert "10:30" in times and "11:30" in times


async def test_double_booking_is_rejected(db):
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)
    await book(business, haircut, at(day, "15:00"))

    with pytest.raises(BookingError, match="already booked"):
        await book(business, haircut, at(day, "15:15"), phone="9999999999")


async def test_database_constraint_stops_concurrent_double_booking(db, monkeypatch):
    """Simulate the race: both requests pass the application's availability check before
    either commits. Only the Postgres exclusion constraint can stop the second booking."""
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)

    async def no_conflicts(*args, **kwargs):
        return []

    monkeypatch.setattr(booking, "_busy_intervals", no_conflicts)

    results = await asyncio.gather(
        book(business, haircut, at(day, "12:00"), phone="1111111111"),
        book(business, haircut, at(day, "12:00"), phone="2222222222"),
        return_exceptions=True,
    )

    errors = [r for r in results if isinstance(r, BookingError)]
    assert len(errors) == 1, results
    assert "just booked by someone else" in str(errors[0])


@pytest.mark.parametrize(
    ("hhmm", "message"),
    [("09:30", "doesn't fit our hours"), ("17:45", "doesn't fit our hours")],
)
async def test_booking_outside_hours_is_rejected(db, hhmm, message):
    business, haircut = await create_salon()
    with pytest.raises(BookingError, match=message):
        await book(business, haircut, at(next_weekday(TUESDAY), hhmm))


async def test_booking_on_closed_day_is_rejected(db):
    business, haircut = await create_salon()
    with pytest.raises(BookingError, match="closed on Mondays"):
        await book(business, haircut, at(next_weekday(MONDAY), "11:00"))


async def test_cancel_requires_matching_phone(db):
    business, haircut = await create_salon()
    created = await book(business, haircut, at(next_weekday(TUESDAY), "10:00"), phone="98765 43210")

    async with SessionLocal() as session:
        with pytest.raises(BookingError, match="couldn't find"):
            await booking.cancel_booking(session, business.id, created.id, "1234567890")
        # Same number written differently still matches after normalisation.
        cancelled = await booking.cancel_booking(session, business.id, created.id, "9876543210")

    assert cancelled.status == BookingStatus.CANCELLED


async def test_cancelled_slot_becomes_available_again(db):
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)
    created = await book(business, haircut, at(day, "13:00"))

    async with SessionLocal() as session:
        await booking.cancel_booking(session, business.id, created.id, "9876543210")

    await book(business, haircut, at(day, "13:00"), phone="5555555555")  # no error


async def test_reschedule_moves_booking_and_frees_old_slot(db):
    business, haircut = await create_salon()
    day = next_weekday(TUESDAY)
    created = await book(business, haircut, at(day, "10:00"))

    async with SessionLocal() as session:
        moved = await booking.reschedule_booking(
            session, business, created.id, "9876543210", at(day, "16:00")
        )
    assert booking.to_local(business, moved.start_at).strftime("%H:%M") == "16:00"

    await book(business, haircut, at(day, "10:00"), phone="5555555555")  # old slot is free


def test_normalize_phone():
    assert booking.normalize_phone("98765 43210") == "9876543210"
    assert booking.normalize_phone("+91 98765-43210") == "+919876543210"
    with pytest.raises(BookingError):
        booking.normalize_phone("123")
