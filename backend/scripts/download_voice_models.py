"""Download the local voice models (one-time, ~250 MB total). Safe to re-run.

    uv run python -m scripts.download_voice_models

- Kokoro TTS (int8 ONNX, ~88 MB) + voices (~27 MB) → backend/data/models/
- faster-whisper STT model (~145 MB for base.en) → Hugging Face cache
"""

from pathlib import Path

import httpx

from app.config import get_settings

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"✓ {dest.name} already present")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=None) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {dest.name}: {done * 100 // total}%", end="", flush=True)
    tmp.rename(dest)  # only a complete download gets the real name
    print(f"\r✓ {dest.name} ({done / 1e6:.0f} MB)")


def main() -> None:
    s = get_settings()
    models = Path(s.voice_models_dir)
    models.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        download(f"{KOKORO_RELEASE}/{name}", models / name)

    print(f"Fetching Whisper '{s.whisper_model}' (first time only)…")
    from faster_whisper import WhisperModel

    WhisperModel(s.whisper_model, device="cpu", compute_type="int8")
    print("✓ Whisper ready")


if __name__ == "__main__":
    main()
