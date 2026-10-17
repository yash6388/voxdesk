"""Input guardrails, applied before a customer message reaches any LLM.

Cheap, deterministic checks — they cost nothing and run in microseconds:
- message length (huge inputs = cost/latency abuse)
- common prompt-injection phrasing ("ignore previous instructions", "reveal your
  system prompt", role/format injection…)

These are a first line of defence, not the only one: tenant scoping lives in code (MCP
headers), writes need human confirmation, and tools validate their inputs. An ML
classifier (e.g. Llama Prompt Guard) could be added behind the same interface.
"""

import re
from dataclasses import dataclass

MAX_MESSAGE_CHARS = 2000

_INJECTION = re.compile(
    r"|".join(
        [
            # "ignore all previous instructions", "disregard your prompt"…
            r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|your)\b"
            r".{0,20}\b(instructions?|prompts?|guidelines|directives)\b",
            # "ignore your rules" — but not "my previous booking rules"
            r"\b(ignore|disregard|forget|override)\s+(all\s+)?(of\s+)?your\s+rules\b",
            # "reveal your system prompt", "show me your instructions"
            r"\b(reveal|show|print|repeat|output|tell me)\b.{0,20}"
            r"\b(system|hidden|initial)\s+(prompt|instructions?)\b",
            r"\b(reveal|show|print|repeat|output)\b.{0,15}\byour\s+(instructions|prompt|rules)\b",
            r"\byou are now\b",
            r"\b(developer|god|jailbreak|dan)\s+mode\b",
            r"\bact as\b.{0,20}\b(system|admin|developer|unrestricted)\b",
            r"<\|?(im_start|im_end|system)\|?>",  # chat-template tokens
            r"^\s*(system|assistant)\s*:",  # role injection at the start of a line
            r"\bnew instructions?\s*:",
        ]
    ),
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None  # "too_long" | "prompt_injection"
    reply: str | None = None  # what to tell the customer instead


def check_message(text: str, business_name: str) -> Verdict:
    if len(text) > MAX_MESSAGE_CHARS:
        return Verdict(
            False,
            "too_long",
            "That message is a bit long for me — could you ask in a shorter way?",
        )
    if _INJECTION.search(text):
        return Verdict(
            False,
            "prompt_injection",
            f"I can only help with questions about {business_name} — like our services, "
            "prices, opening hours, or booking an appointment.",
        )
    return Verdict(True)
