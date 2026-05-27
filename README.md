# phone-agent

A voice agent that auto-answers iCloud Continuity calls on a Mac and runs a real-time conversation with the caller — Claude Haiku 4.5 for reasoning, [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) for text-to-speech, [Parakeet (MLX)](https://github.com/senstella/parakeet-mlx) for speech-to-text, [Hammerspoon](https://www.hammerspoon.org/) + [BlackHole](https://existential.audio/blackhole/) for call detection and audio routing.

Built as a proof-of-concept receptionist that picks up while you're unavailable, finds out who's calling, takes a message, and saves a transcript. The eventual goal is hands-off phone capability for an autonomous Claude agent running on a dedicated Mac Mini.

## What works

- **Auto-answer** every incoming Continuity call. AX-driven click of the `FACETIME_NOTIFICATION` banner — no UI flicker.
- **Hands-off audio routing**. On answer, Hammerspoon snapshots your system audio defaults, swaps to BlackHole, and selects BlackHole 2ch as Phone.app's mic. On hangup, it restores everything.
- **Streaming pipeline**. Claude tokens stream → sentence-chunked Kokoro synthesis → background audio player. First-sentence latency is ~600–800 ms after the caller stops talking.
- **Barge-in**. Caller can interrupt mid-reply; the agent stops cleanly, history is truncated so the model doesn't "remember" saying things the caller never heard.
- **Per-call transcripts** saved to `transcripts/` as JSON.

## Status: prototype, macOS-only, single-user

Tested on macOS 26.4.1 / Apple M5 / Python 3.11. The Phone.app AX hierarchy is the most fragile piece — any macOS major-version upgrade may break call detection. See `hammerspoon/ax_inspector.lua` for the diagnostic dumper.

## Prerequisites

- macOS 14+ (Sonoma) — built and tested on macOS 26 (Tahoe)
- Apple Silicon Mac (Parakeet-MLX is M-series only)
- iPhone signed into the same iCloud account, with **Calls on Other Devices** → ON for this Mac (Settings → Apps → Phone)
- An Anthropic API key
- Homebrew

## Setup

```bash
# 1. Clone
git clone <your fork of this repo>
cd phone-agent

# 2. Install BlackHole virtual audio (2ch + 16ch)
brew install --cask blackhole-2ch blackhole-16ch
# Restart coreaudiod once so the new HAL plugins load:
sudo killall coreaudiod

# 3. Install Hammerspoon and symlink this project's config
brew install --cask hammerspoon
ln -s "$PWD/hammerspoon" ~/.hammerspoon
# Launch Hammerspoon once and grant Accessibility permission when prompted
open -a Hammerspoon

# 4. Python venv + deps (uv recommended)
uv venv
uv pip install -r requirements.txt

# 5. Download the Kokoro TTS model (~350 MB)
./scripts/download_models.sh
# (Parakeet model auto-downloads on first use)

# 6. Configure secrets
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and OWNER_NAME
```

## Running

```bash
# Start the receptionist daemon — leave it running
python -m agent.receptionist
```

The daemon polls `/tmp/phone-agent-call.json`, which Hammerspoon writes when it auto-answers a call. On detection it runs the conversation loop and writes a transcript on call-end.

Hammerspoon hotkeys (defined in `hammerspoon/init.lua`):

| Hotkey | What |
|---|---|
| `⌥⌃⌘+T` | Toggle auto-answer on/off |
| `⌥⌃⌘+↩` | Manually press Answer (if auto-answer off) |
| `⌥⌃⌘+D` | Decline current call |
| `⌥⌃⌘+P` | Probe current call banner (read-only) |
| `⌥⌃⌘+S` | Print auto-answer / poll status |
| `⌥⌃⌘+E` / `⌥⌃⌘+R` | Manually engage / restore call audio routing |
| `⌥⌃⌘+I` | Dump audio devices to `logs/audio-devices.log` |
| `⌥⌃⌘+A` | Dump full AX hierarchy of call-related processes |
| `⌥⌃⌘+L` | List which candidate processes are running |

## Architecture at a glance

```
Continuity call rings
  └─ Hammerspoon
       ├─ call_handler.lua  : finds FACETIME_NOTIFICATION banner, presses Answer
       ├─ auto_answer.lua   : poll loop, "already pressed" tracking
       ├─ call_audio.lua    : snapshot+swap defaults, click Phone.app→Video→BlackHole 2ch
       └─ call_state.lua    : write /tmp/phone-agent-call.json
            ↓
Python daemon (agent/receptionist.py)
  ├─ MicMonitor       : single InputStream, fans chunks to N subscriber queues
  ├─ listen()         : VAD-bounded capture from a subscriber queue
  ├─ Recognizer       : Parakeet-MLX, transcribe WAV
  ├─ Conversation     : Anthropic streaming, history with consecutive-user merge
  ├─ stream_to_player : sentence-chunked Kokoro synth, push to AudioPlayer
  ├─ AudioPlayer      : background thread, sd.play, tracks started vs fully_played
  └─ BargeInWatcher   : own mic subscription, fires if player.is_busy() and 200ms speech
       ↓
Banner clears (caller hung up)
  └─ Hammerspoon: restore defaults, delete state file
       └─ daemon: save transcript, idle for next call
```

## Caveats and known limits

- **Continuity is flaky.** Calls-on-other-devices toggles drop off after iOS updates. If the Mac stops ringing, check the iPhone Phone settings.
- **Same-room echo.** If the calling phone is near the Mac, its mic picks up the Mac speakers (Phone.app outputs a "monitor" feed there in addition to your selected output device). Mute system volume when testing.
- **Phone.app's mic selection is per-call, not sticky.** Hammerspoon clicks "BlackHole 2ch" every time auto-answer fires. If a future macOS update changes that menu structure, the click will silently fail — you'd hear the agent's TTS through your Mac speakers and the caller would hear silence.
- **Half-duplex, sentence-grained.** The barge-in detector fires after 200 ms of sustained caller voice. Sub-200ms interjections are missed.
- **No outbound dialing yet.** This branch only handles inbound.

## License

MIT — see `LICENSE` (add your own if you want).
