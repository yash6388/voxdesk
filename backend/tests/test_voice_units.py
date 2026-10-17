import json

import httpx
import numpy as np
import pytest

from app.voice.audio import decode_to_mono_16k, to_wav
from app.voice.providers import ElevenLabsSTT, ElevenLabsTTS
from app.voice.text import SentenceSplitter, speakable, spoken_decision


def stream(splitter: SentenceSplitter, text: str) -> list[str]:
    out = []
    for token in text.split(" "):
        out += splitter.feed(token + " ")
    return out + splitter.flush()


def test_sentences_are_released_as_soon_as_complete():
    splitter = SentenceSplitter()
    assert splitter.feed("A keratin treatment costs ₹6,500 [1]. It ") == [
        "A keratin treatment costs ₹6,500 [1]."
    ]
    assert splitter.feed("takes 3 hours.") == []  # no trailing space yet: might continue
    assert splitter.flush() == ["It takes 3 hours."]


def test_short_fragments_join_the_next_sentence_and_decimals_dont_split():
    sentences = stream(SentenceSplitter(), "Sure! It takes 2.5 hours. Anything else?")
    assert sentences == ["Sure! It takes 2.5 hours.", "Anything else?"]


def test_speakable_text():
    assert speakable("It costs ₹6,500 [1, 2] and **INR 1,200** for kids [3].") == (
        "It costs 6,500 rupees and 1,200 rupees for kids."
    )


@pytest.mark.parametrize(
    ("said", "decision"),
    [
        ("yes please", True),
        ("Yeah, go ahead", True),
        ("haan", True),
        ("no, wait", False),
        ("yes… actually no", False),  # any "no" wins — the safe default
        ("the blue one", None),
    ],
)
def test_spoken_decision(said, decision):
    assert spoken_decision(said) is decision


def test_decode_resamples_to_16k_mono():
    tone = np.sin(np.linspace(0, 2 * np.pi * 440, 24_000)).astype(np.float32)  # 1 s @ 24 kHz
    samples = decode_to_mono_16k(to_wav(tone, 24_000))
    assert samples.dtype == np.float32
    assert abs(len(samples) - 16_000) < 200


async def test_elevenlabs_tts_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(
            path=request.url.path,
            key=request.headers["xi-api-key"],
            fmt=request.url.params["output_format"],
            body=json.loads(request.content),
        )
        return httpx.Response(200, content=b"MP3")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://el")
    speech = await ElevenLabsTTS("k", "voice-1", "eleven_flash_v2_5", http=http).synthesize("Hi")

    assert speech.audio == b"MP3" and speech.mime == "audio/mpeg"
    assert seen == {
        "path": "/text-to-speech/voice-1",
        "key": "k",
        "fmt": "mp3_44100_128",
        "body": {"text": "Hi", "model_id": "eleven_flash_v2_5"},
    }


async def test_elevenlabs_stt_request():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/speech-to-text"
        assert request.headers["xi-api-key"] == "k"
        assert b'name="model_id"' in request.content and b"scribe_v1" in request.content
        return httpx.Response(200, json={"text": " Book a haircut "})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://el")
    assert await ElevenLabsSTT("k", "scribe_v1", http=http).transcribe(b"webm") == "Book a haircut"
