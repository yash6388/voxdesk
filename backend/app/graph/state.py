from typing import Literal

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field

Intent = Literal["knowledge", "booking", "smalltalk"]


class ChatState(MessagesState):
    """Graph state, checkpointed to Postgres after every node.

    `messages` (from MessagesState) accumulates the conversation across turns;
    the other fields are set per turn.
    """

    business_id: str
    business_name: str
    business_description: str
    business_timezone: str
    intent: Intent
    search_query: str
    context: list[dict]


class Route(BaseModel):
    """Router output: what the customer wants, plus a standalone search query."""

    intent: Intent = Field(
        description=(
            "knowledge: a question about the business (services, prices, hours, policies). "
            "booking: wants to book, reschedule, cancel or check an appointment, OR is "
            "continuing a booking conversation (choosing a service or time, giving their "
            "name or phone number, answering the assistant's booking question). "
            "smalltalk: greetings, thanks, or anything else."
        )
    )
    search_query: str = Field(
        description=(
            "The customer's latest question rewritten to be self-contained, resolving "
            "references to earlier messages (e.g. 'and on Sundays?' -> 'opening hours on "
            "Sundays'). Empty if intent is not knowledge."
        )
    )
