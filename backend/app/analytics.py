"""Records each conversation turn for the Inbox and Analytics.

The recorder watches the same event stream the browser receives (route, token, confirm,
tool_result, handoff, guardrail, error…) and derives the turn's outcome — so it needs no
knowledge of how the graph or agents work internally. Saving never breaks a conversation:
failures are logged and swallowed.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from app.db.models import Conversation, ConversationStatus, Turn
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

OUTCOMES = (
    "answered",
    "booking_pending",
    "booked",
    "booking_declined",
    "guardrail",
    "handoff",
    "error",
)


class TurnRecorder:
    def __init__(
        self,
        business_id: uuid.UUID | str,
        thread_id: str,
        channel: str,
        user_text: str,
        declined: bool = False,
        intent: str | None = None,
    ):
        self.business_id = uuid.UUID(str(business_id))
        self.thread_id = thread_id
        self.channel = channel
        self.user_text = user_text
        # Confirmation turns (resume) skip the router, so the caller states the intent.
        self.intent: str | None = intent
        self._reply: list[str] = []
        self._flags: set[str] = {"booking_declined"} if declined else set()
        self.handoff_reason: str | None = None

    def observe(self, event: str, data) -> None:
        if event == "route":
            self.intent = data.get("intent")
        elif event == "token":
            self._reply.append(data.get("text", ""))
        elif event == "confirm":
            self._flags.add("booking_pending")
        elif event == "tool_result" and data.get("name") == "book_appointment":
            if data.get("status") == "success":
                self._flags.add("booked")
        elif event == "decision" and data.get("approved") is False:
            self._flags.add("booking_declined")
        elif event == "handoff":
            self._flags.add("handoff")
            self.handoff_reason = data.get("reason")
        elif event in ("guardrail", "error"):
            self._flags.add(event)

    @property
    def reply(self) -> str:
        return "".join(self._reply)

    @property
    def outcome(self) -> str:
        for flag in (
            "guardrail",
            "error",
            "handoff",
            "booked",
            "booking_declined",
            "booking_pending",
        ):
            if flag in self._flags:
                return flag
        return "answered"

    async def save(
        self, first_token_ms: float | None = None, total_ms: float | None = None
    ) -> None:
        try:
            async with SessionLocal() as session:
                now = datetime.now(UTC)
                values = {
                    "id": uuid.uuid4(),
                    "business_id": self.business_id,
                    "thread_id": self.thread_id,
                    "channel": self.channel,
                    "turn_count": 1,
                    "last_activity_at": now,
                }
                update = {
                    "turn_count": Conversation.turn_count + 1,
                    "last_activity_at": now,
                }
                if self.outcome == "handoff":
                    values |= {
                        "status": ConversationStatus.NEEDS_HUMAN,
                        "handoff_reason": self.handoff_reason,
                    }
                    update |= {
                        "status": ConversationStatus.NEEDS_HUMAN,
                        "handoff_reason": self.handoff_reason,
                    }
                # One atomic upsert: create the conversation on its first turn, update it after.
                stmt = (
                    insert(Conversation)
                    .values(**values)
                    .on_conflict_do_update(constraint="uq_conversations_thread", set_=update)
                    .returning(Conversation.id)
                )
                conversation_id = await session.scalar(stmt)
                session.add(
                    Turn(
                        conversation_id=conversation_id,
                        business_id=self.business_id,
                        intent=self.intent,
                        outcome=self.outcome,
                        user_text=self.user_text[:500],
                        reply_text=self.reply[:1000],
                        first_token_ms=round(first_token_ms)
                        if first_token_ms is not None
                        else None,
                        total_ms=round(total_ms) if total_ms is not None else None,
                    )
                )
                await session.commit()
        except Exception:
            logger.warning("Could not record turn analytics", exc_info=True)
