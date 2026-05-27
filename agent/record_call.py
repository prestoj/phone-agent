"""Record audio from a chosen device to a WAV file, then play it back through default output.

Usage: python record_call.py [device-name-substring] [seconds] [output-wav-path]
Default: 'BlackHole 16ch', 8 seconds, /tmp/call-capture.wav.
"""
import sys
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


def find_input_device(name_substring: str) -> int:
    devices = sd.query_devices()
    matches = [
        (i, d) for i, d in enumerate(devices)
        if name_substring.lower() in d["name"].lower()
        and d["max_input_channels"] > 0
    ]
    if not matches:
        names = ", ".join(d["name"] for d in devices if d["max_input_channels"] > 0)
        raise SystemExit(f"No input device matching {name_substring!r}. Input devices: {names}")
    return matches[0][0]


def find_default_output_excluding(exclude_substring: str) -> int:
    """Find a sensible playback device that is NOT BlackHole (otherwise user hears nothing)."""
    devices = sd.query_devices()
    for preferred in ("MacBook Air Speakers", "MacBook Pro Speakers", "Built-in"):
        for i, d in enumerate(devices):
            if preferred.lower() in d["name"].lower() and d["max_output_channels"] > 0:
                return i
    for i, d in enumerate(devices):
        if (
            d["max_output_channels"] > 0
            and exclude_substring.lower() not in d["name"].lower()
        ):
            return i
    raise SystemExit("No non-BlackHole output device found for playback.")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "BlackHole 16ch"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    out_path = Path(sys.argv[3] if len(sys.argv) > 3 else "/tmp/call-capture.wav")
    samplerate = 48000

    in_idx = find_input_device(target)
    in_info = sd.query_devices(in_idx)
    channels = min(2, in_info["max_input_channels"])
    print(f"← recording {seconds:.1f}s from [{in_idx}] {in_info['name']!r} (channels={channels})")

    audio = sd.rec(
        int(seconds * samplerate),
        samplerate=samplerate,
        channels=channels,
        device=in_idx,
        dtype="float32",
        blocking=True,
    )

    sf.write(str(out_path), audio, samplerate)
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"saved {out_path}  peak={peak:.4f}  rms={rms:.4f}")
    if peak < 0.001:
        print("⚠️  Capture was effectively silent — caller audio probably not routed to this device.")

    out_idx = find_default_output_excluding("BlackHole")
    out_info = sd.query_devices(out_idx)
    print(f"→ playing capture back through [{out_idx}] {out_info['name']!r}")
    sd.play(audio, samplerate=samplerate, device=out_idx, blocking=True)
    print("done")


if __name__ == "__main__":
    main()
