from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.booking import service as booking
from app.db.models import Business, Service
from app.db.session import SessionLocal

TZ = "Asia/Kolkata"


def next_weekday(weekday: int, min_days_ahead: int = 2) -> date:
    """The next date falling on `weekday` (0 = Monday) at least `min_days_ahead` days away."""
    day = datetime.now(ZoneInfo(TZ)).date() + timedelta(days=min_days_ahead)
    return day + timedelta(days=(weekday - day.weekday()) % 7)


async def create_salon() -> tuple[Business, Service]:
    """A business open Tue–Sun 10:00–18:00 (closed Monday) with a 30-minute haircut."""
    async with SessionLocal() as session:
        business = Business(name="Test Salon", timezone=TZ)
        session.add(business)
        await session.flush()
        haircut = Service(business_id=business.id, name="Haircut", duration_minutes=30, price=500)
        session.add(haircut)
        await session.commit()
        await booking.set_hours(
            session, business.id, [(d, time(10), time(18)) for d in range(1, 7)]
        )
        return business, haircut


def at(day: date, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day.isoformat()}T{hhmm}")
