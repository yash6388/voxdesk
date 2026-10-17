from langchain_core.messages import AnyMessage

# How many past messages the LLM sees. Older ones stay in the checkpoint but
# aren't sent, which bounds latency and token cost on long conversations.
HISTORY_WINDOW = 10


def conversation_view(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Only what was actually said: customer messages and assistant replies with text.
    Tool calls/results are internal; dropping them also avoids sending the LLM a tool
    result whose matching call was cut off by the history window."""
    return [
        m
        for m in messages
        if m.type == "human" or (m.type == "ai" and m.text and not getattr(m, "tool_calls", None))
    ]


def recent_turns(messages: list[AnyMessage], turns: int) -> list[AnyMessage]:
    """The last `turns` turns in full, including tool calls and their results.
    Cutting at a customer message keeps every tool call paired with its result."""
    starts = [i for i, m in enumerate(messages) if m.type == "human"]
    return messages[starts[-turns] :] if len(starts) >= turns else messages
