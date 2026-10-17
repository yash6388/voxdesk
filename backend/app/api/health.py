import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.db.session import SessionLocal

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_S = 2.0


class HealthResponse(BaseModel):
    status: str
    environment: str


class ServiceHealth(BaseModel):
    name: str
    status: Literal["up", "down"]
    latency_ms: float | None = None
    detail: str | None = None


class ServicesHealth(BaseModel):
    status: Literal["ok", "degraded"]
    services: list[ServiceHealth]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: is the API process itself up? Used by Docker, CI and load balancers."""
    return HealthResponse(status="ok", environment=get_settings().environment)


async def _check(name: str, probe: Callable[[], Awaitable[str | None]]) -> ServiceHealth:
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(probe(), timeout=CHECK_TIMEOUT_S)
        status = "up"
    except Exception as exc:  # any failure (refused, timeout, bad status) means "down"
        detail, status = type(exc).__name__, "down"
    return ServiceHealth(
        name=name,
        status=status,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        detail=detail,
    )


@router.get("/health/services", response_model=ServicesHealth)
async def services_health() -> ServicesHealth:
    """Readiness: can the API reach everything it depends on? Checks run in parallel,
    each with a short timeout, so one dead service can't make this endpoint hang."""
    s = get_settings()

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as http:

        async def database() -> str:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return "postgres"

        async def mcp_server() -> str:
            base = s.mcp_url.removesuffix("/mcp")
            (await http.get(f"{base}/health")).raise_for_status()
            return "7 booking tools"

        def agent(url: str) -> Callable[[], Awaitable[str]]:
            async def probe() -> str:
                # The public Agent Card doubles as a health check for an A2A agent.
                response = await http.get(f"{url}{AGENT_CARD_WELL_KNOWN_PATH}")
                response.raise_for_status()
                return response.json()["name"]

            return probe

        services = await asyncio.gather(
            _check("database", database),
            _check("mcp_server", mcp_server),
            _check("knowledge_agent", agent(s.knowledge_agent_url)),
            _check("booking_agent", agent(s.booking_agent_url)),
        )

    status = "ok" if all(x.status == "up" for x in services) else "degraded"
    return ServicesHealth(status=status, services=list(services))
