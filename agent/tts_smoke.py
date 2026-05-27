"""Synthesize a greeting with Kokoro and play it to a chosen output device.

Usage: python tts_smoke.py [device-name-substring] ["text to speak"]
Defaults: device='MacBook Air Speakers', text=a sample greeting.
Pass device='BlackHole 2ch' to inject into a live call.
"""
import sys
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from kokoro_onnx import Kokoro

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "kokoro-v1.0.onnx"
VOICES_PATH = PROJECT_ROOT / "models" / "voices-v1.0.bin"

DEFAULT_TEXT = (
    "Hello, this is a smoke test of the Kokoro text-to-speech engine. "
    "If you hear this sentence clearly, the synthesis pipeline is working."
)


def find_output_device(name_substring: str) -> int:
    devices = sd.query_devices()
    matches = [
        (i, d) for i, d in enumerate(devices)
        if name_substring.lower() in d["name"].lower()
        and d["max_output_channels"] > 0
    ]
    if not matches:
        names = ", ".join(d["name"] for d in devices if d["max_output_channels"] > 0)
        raise SystemExit(f"No output device matching {name_substring!r}. Options: {names}")
    return matches[0][0]


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "MacBook Air Speakers"
    text = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TEXT

    if not MODEL_PATH.exists() or not VOICES_PATH.exists():
        raise SystemExit(f"Missing model files at {MODEL_PATH} / {VOICES_PATH}")

    print(f"loading kokoro from {MODEL_PATH.name}...")
    kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))

    print(f"synthesizing: {text!r}")
    samples, sample_rate = kokoro.create(text, voice="af_heart", speed=1.0, lang="en-us")
    samples = np.asarray(samples, dtype=np.float32)
    duration = len(samples) / sample_rate
    print(f"got {duration:.2f}s of audio at {sample_rate}Hz")

    out_path = Path("/tmp/tts-greeting.wav")
    sf.write(str(out_path), samples, sample_rate)
    print(f"saved {out_path}")

    out_idx = find_output_device(target)
    info = sd.query_devices(out_idx)
    print(f"→ playing through [{out_idx}] {info['name']!r}")
    sd.play(samples, samplerate=sample_rate, device=out_idx, blocking=True)
    print("done")


if __name__ == "__main__":
    main()
