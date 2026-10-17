"""Owner-facing endpoints: manage services, opening hours and view bookings.
(Customers book through the agent, which uses the MCP server.)"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import selectinload

from app.api.businesses import get_business_or_404
from app.api.deps import SessionDep
from app.booking import service as booking
from app.db.models import Booking, BookingStatus, Service
from app.schemas import BookingOut, HoursDay, HoursUpdate, ServiceCreate, ServiceOut

router = APIRouter(prefix="/businesses/{business_id}", tags=["booking"])


@router.get("/services", response_model=list[ServiceOut])
async def list_services(business_id: uuid.UUID, session: SessionDep):
    await get_business_or_404(business_id, session)
    return await booking.list_services(session, business_id, include_inactive=True)


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(business_id: uuid.UUID, body: ServiceCreate, session: SessionDep):
    await get_business_or_404(business_id, session)
    service = Service(business_id=business_id, **body.model_dump())
    session.add(service)
    await session.commit()
    return service


@router.patch("/services/{service_id}", response_model=ServiceOut)
async def set_service_active(
    business_id: uuid.UUID, service_id: uuid.UUID, active: bool, session: SessionDep
):
    """Activate/deactivate. Services are never hard-deleted so past bookings keep them."""
    service = await session.get(Service, service_id)
    if service is None or service.business_id != business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    service.active = active
    await session.commit()
    return service


@router.get("/hours", response_model=list[HoursDay])
async def get_hours(business_id: uuid.UUID, session: SessionDep):
    await get_business_or_404(business_id, session)
    return await booking.get_hours(session, business_id)


@router.put("/hours", response_model=list[HoursDay])
async def set_hours(business_id: uuid.UUID, body: HoursUpdate, session: SessionDep):
    await get_business_or_404(business_id, session)
    week = [(d.weekday, d.opens_at, d.closes_at) for d in body.days]
    return await booking.set_hours(session, business_id, week)


def _booking_out(b: Booking) -> BookingOut:
    return BookingOut(
        id=b.id,
        service_name=b.service.name,
        customer_name=b.customer_name,
        customer_phone=b.customer_phone,
        start_at=b.start_at,
        end_at=b.end_at,
        status=b.status,
        created_at=b.created_at,
    )


@router.get("/bookings", response_model=list[BookingOut])
async def list_bookings(business_id: uuid.UUID, session: SessionDep):
    await get_business_or_404(business_id, session)
    return [_booking_out(b) for b in await booking.list_bookings(session, business_id)]


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
async def cancel_booking(business_id: uuid.UUID, booking_id: uuid.UUID, session: SessionDep):
    """Owner cancellation (no phone check, unlike the customer-facing MCP tool)."""
    found = await session.get(Booking, booking_id, options=[selectinload(Booking.service)])
    if found is None or found.business_id != business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    found.status = BookingStatus.CANCELLED
    await session.commit()
    return _booking_out(found)
