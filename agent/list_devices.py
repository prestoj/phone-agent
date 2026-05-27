"""List audio devices visible to PortAudio (via sounddevice)."""
import sounddevice as sd


def main() -> None:
    devices = sd.query_devices()
    default_in_idx, default_out_idx = sd.default.device

    print(f"PortAudio version: {sd.get_portaudio_version()}")
    print(f"Default input idx:  {default_in_idx}")
    print(f"Default output idx: {default_out_idx}")
    print()
    print(f"{'idx':>3}  {'name':<40}  {'in':>2} {'out':>3}  hostapi      default_sr  default")
    print("-" * 95)
    for i, d in enumerate(devices):
        marker = ""
        if i == default_in_idx:
            marker += " ←IN"
        if i == default_out_idx:
            marker += " ←OUT"
        print(
            f"{i:>3}  {d['name']:<40}  "
            f"{d['max_input_channels']:>2} {d['max_output_channels']:>3}  "
            f"{sd.query_hostapis(d['hostapi'])['name']:<12} "
            f"{int(d['default_samplerate']):>10}{marker}"
        )


if __name__ == "__main__":
    main()
