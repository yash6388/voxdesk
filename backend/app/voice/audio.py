import io

import av
import numpy as np
import soundfile as sf

WHISPER_RATE = 16_000


def decode_to_mono_16k(data: bytes) -> np.ndarray:
    """Decode any browser/container format (webm/opus, ogg, wav, mp3…) to 16 kHz mono
    float32 — what Whisper expects. Done here with PyAV directly rather than through
    faster-whisper's helper, which is incompatible with current PyAV releases."""
    resampler = av.AudioResampler(format="flt", layout="mono", rate=WHISPER_RATE)
    chunks: list[np.ndarray] = []
    with av.open(io.BytesIO(data)) as container:
        for frame in container.decode(audio=0):
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
    chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))  # flush
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
