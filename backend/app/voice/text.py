"""Text helpers for speech: split a token stream into sentences, make text speakable,
and understand spoken yes/no answers to a confirmation."""

import re

# A sentence ends at . ! ? followed by whitespace — but not inside numbers like "6.5".
_SENTENCE_END = re.compile(r"(?<!\d)[.!?](?=\s)|(?<=\d)[.!?](?=\s+[A-Z])")


class SentenceSplitter:
    """Feed streamed LLM tokens; get back complete sentences as soon as they exist,
    so speech can start before the whole answer has been generated."""

    def __init__(self, min_chars: int = 12):
        self._buffer = ""
        self._min = min_chars

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = []
        start = 0
        for match in _SENTENCE_END.finditer(self._buffer):
            end = match.end()
            candidate = self._buffer[start:end].strip()
            # Very short fragments ("Hi.") are kept with the next sentence for natural prosody.
            if len(candidate) >= self._min:
                sentences.append(candidate)
                start = end
        self._buffer = self._buffer[start:]
        return sentences

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []


# [1], [1, 2] and the full-width 【1】 some models (e.g. gpt-oss) use.
_CITATION = re.compile(r"\s*(?:\[\d+(?:,\s*\d+)*\]|【\d+(?:,\s*\d+)*】)")
_MARKDOWN = re.compile(r"[*_#`>]+")
_RUPEES = re.compile(r"₹\s?([\d,]+(?:\.\d+)?)")
_INR = re.compile(r"\bINR\s?([\d,]+(?:\.\d+)?)")


def speakable(text: str) -> str:
    """What should be *said*: no citation markers, no markdown, currency read naturally."""
    text = _CITATION.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = _RUPEES.sub(r"\1 rupees", text)
    text = _INR.sub(r"\1 rupees", text)
    return re.sub(r"\s+", " ", text).strip()


_YES = re.compile(
    r"\b(yes|yeah|yep|yup|sure|confirm(ed)?|ok(ay)?|go ahead|do it|please do|correct|"
    r"that'?s right|haan|ha)\b",
    re.IGNORECASE,
)
_NO = re.compile(
    r"\b(no|nope|nah|don'?t|do not|cancel|stop|wait|not now|nahi|mat)\b", re.IGNORECASE
)


def spoken_decision(transcript: str) -> bool | None:
    """Interpret a spoken reply to "Shall I book this?". None = unclear (ask again).
    A "no" anywhere wins, so "yes… actually no, wait" is treated as no."""
    if _NO.search(transcript):
        return False
    if _YES.search(transcript):
        return True
    return None
