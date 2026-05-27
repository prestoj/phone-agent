"""Transcribe a WAV file with Parakeet (MLX).

Usage: python stt_smoke.py [wav-path] [--gain N]
Default: /tmp/tts-greeting.wav, no gain.
"""
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from parakeet_mlx import from_pretrained


MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v2"


def parse_args(argv: list[str]) -> tuple[Path, float]:
    args = argv[1:]
    gain = 1.0
    paths: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--gain" and i + 1 < len(args):
            gain = float(args[i + 1])
            i += 2
        else:
            paths.append(args[i])
            i += 1
    path = Path(paths[0]) if paths else Path("/tmp/tts-greeting.wav")
    return path, gain


def main() -> None:
    wav_path, gain = parse_args(sys.argv)
    if not wav_path.exists():
        raise SystemExit(f"WAV not found: {wav_path}")

    audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio ** 2)))
    duration = len(audio) / sr
    print(f"loaded {wav_path}  duration={duration:.2f}s  sr={sr}  peak={peak:.4f}  rms={rms:.4f}")

    transcribe_path = wav_path
    if gain != 1.0:
        boosted = np.clip(audio * gain, -1.0, 1.0)
        tmp = Path("/tmp/stt-input.wav")
        sf.write(str(tmp), boosted, sr)
        print(f"applied gain x{gain}  →  peak={float(np.abs(boosted).max()):.4f}  (wrote {tmp})")
        transcribe_path = tmp

    print(f"loading Parakeet model: {MODEL_ID}")
    t0 = time.monotonic()
    model = from_pretrained(MODEL_ID)
    print(f"  loaded in {time.monotonic() - t0:.2f}s")

    print("transcribing...")
    t0 = time.monotonic()
    result = model.transcribe(str(transcribe_path))
    elapsed = time.monotonic() - t0
    text = result.text if hasattr(result, "text") else str(result)
    rtf = elapsed / max(duration, 0.001)
    print(f"  transcribed in {elapsed:.2f}s  (RTF={rtf:.2f}x)")
    print()
    print("TRANSCRIPT:")
    print(f"  {text!r}")


if __name__ == "__main__":
    main()
