"""Play a 1kHz sine wave to a chosen audio device.

Usage: python play_tone.py [device-name-substring] [seconds]
Default: 'BlackHole 2ch', 3 seconds.
"""
import sys

import numpy as np
import sounddevice as sd


def find_device(name_substring: str) -> int:
    devices = sd.query_devices()
    matches = [
        (i, d) for i, d in enumerate(devices)
        if name_substring.lower() in d["name"].lower()
        and d["max_output_channels"] > 0
    ]
    if not matches:
        names = ", ".join(d["name"] for d in devices if d["max_output_channels"] > 0)
        raise SystemExit(f"No output device matching {name_substring!r}. Output devices: {names}")
    return matches[0][0]


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "BlackHole 2ch"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    freq = 1000.0
    samplerate = 48000

    device_idx = find_device(target)
    info = sd.query_devices(device_idx)
    print(f"→ playing {freq:.0f}Hz tone for {seconds:.1f}s to [{device_idx}] {info['name']!r}")

    t = np.arange(int(seconds * samplerate)) / samplerate
    tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    stereo = np.column_stack([tone, tone])

    sd.play(stereo, samplerate=samplerate, device=device_idx, blocking=True)
    print("done")


if __name__ == "__main__":
    main()
