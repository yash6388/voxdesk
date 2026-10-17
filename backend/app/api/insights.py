"""Owner-facing Inbox (conversations needing a human) and Analytics."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.auth import OwnedBusiness, owned_business
from app.conversation import graph_config
from app.db.models import Conversation, ConversationStatus, Turn
from app.schemas import AnalyticsOut, ChatMessage, ConversationDetail, ConversationOut

router = APIRouter(
    prefix="/businesses/{business_id}",
    tags=["insights"],
    dependencies=[Depends(owned_business)],
)


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    business: OwnedBusiness,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    since = datetime.now(UTC) - timedelta(days=days)
    in_window = (Turn.business_id == business.id, Turn.created_at >= since)

    def counts(column):
        return select(column, func.count()).where(*in_window).group_by(column)

    outcomes = dict((await session.execute(counts(Turn.outcome))).all())
    intents = {k or "none": v for k, v in (await session.execute(counts(Turn.intent))).all()}
    channels = dict(
        (
            await session.execute(
                select(Conversation.channel, func.count())
                .where(
                    Conversation.business_id == business.id,
                    Conversation.last_activity_at >= since,
                )
                .group_by(Conversation.channel)
            )
        ).all()
    )

    # Days are counted in the business's own timezone, not UTC.
    local_day = func.date(func.timezone(business.timezone, Turn.created_at))
    per_day = {
        day: (turns, conversations)
        for day, turns, conversations in (
            await session.execute(
                select(local_day, func.count(), func.count(func.distinct(Turn.conversation_id)))
                .where(*in_window)
                .group_by(local_day)
            )
        ).all()
    }
    # The day range must use the same timezone as the grouping (found by a test: around
    # midnight UTC vs IST, "today" differed and today's activity fell outside the chart).
    today = datetime.now(ZoneInfo(business.timezone)).date()
    daily = [
        {
            "date": d.isoformat(),
            "turns": per_day.get(d, (0, 0))[0],
            "conversations": per_day.get(d, (0, 0))[1],
        }
        for d in (today - timedelta(days=i) for i in range(min(days, 90) - 1, -1, -1))
    ]

    # Percentiles computed in Postgres.
    p50, p95 = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(Turn.first_token_ms),
                func.percentile_cont(0.95).within_group(Turn.first_token_ms),
            ).where(*in_window, Turn.first_token_ms.is_not(None))
        )
    ).one()

    needs_human = await session.scalar(
        select(func.count()).where(
            Conversation.business_id == business.id,
            Conversation.status == ConversationStatus.NEEDS_HUMAN,
        )
    )
    return AnalyticsOut(
        days=days,
        conversations=sum(channels.values()),
        turns=sum(outcomes.values()),
        bookings=outcomes.get("booked", 0),
        handoffs=outcomes.get("handoff", 0),
        guardrail_blocks=outcomes.get("guardrail", 0),
        errors=outcomes.get("error", 0),
        needs_human_open=needs_human or 0,
        outcomes=outcomes,
        intents=intents,
        channels=channels,
        daily=daily,
        first_token_p50_ms=round(p50) if p50 is not None else None,
        first_token_p95_ms=round(p95) if p95 is not None else None,
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    business: OwnedBusiness,
    session: SessionDep,
    status_filter: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    query = select(Conversation).where(Conversation.business_id == business.id)
    if status_filter:
        query = query.where(Conversation.status == status_filter)
    query = query.order_by(Conversation.last_activity_at.desc()).limit(limit)
    conversations = list(await session.scalars(query))

    # Last customer message per conversation, for the list preview.
    previews = {}
    if conversations:
        latest = (
            select(Turn.conversation_id, func.max(Turn.created_at).label("at"))
            .where(Turn.conversation_id.in_([c.id for c in conversations]))
            .group_by(Turn.conversation_id)
            .subquery()
        )
        rows = await session.execute(
            select(Turn.conversation_id, Turn.user_text).join(
                latest,
                (Turn.conversation_id == latest.c.conversation_id)
                & (Turn.created_at == latest.c.at),
            )
        )
        previews = dict(rows.all())
    return [
        ConversationOut.model_validate(c).model_copy(update={"last_message": previews.get(c.id)})
        for c in conversations
    ]


async def _get_conversation(business_id: uuid.UUID, conversation_id: uuid.UUID, session):
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.business_id != business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    business: OwnedBusiness, conversation_id: uuid.UUID, request: Request, session: SessionDep
):
    """Summary + full transcript (read from the LangGraph checkpoint)."""
    conversation = await _get_conversation(business.id, conversation_id, session)
    snapshot = await request.app.state.graph.aget_state(
        graph_config(business.id, conversation.thread_id)
    )
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    transcript = [
        ChatMessage(role="user" if m.type == "human" else "assistant", content=m.text)
        for m in messages
        if m.type == "human" or (m.type == "ai" and m.text)
    ]
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(), messages=transcript
    )


@router.post("/conversations/{conversation_id}/resolve", response_model=ConversationOut)
async def resolve_conversation(
    business: OwnedBusiness, conversation_id: uuid.UUID, session: SessionDep
):
    conversation = await _get_conversation(business.id, conversation_id, session)
    conversation.status = ConversationStatus.RESOLVED
    await session.commit()
    return conversation
