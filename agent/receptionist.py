"""Phone-agent receptionist daemon (streaming + barge-in capable).

Run once and leave running:
    python -m agent.receptionist

Local debug devices:
    python -m agent.receptionist --input "MacBook Air Microphone" --output "MacBook Air Speakers"
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import re
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import sounddevice as sd
import soundfile as sf
from anthropic import Anthropic
from dotenv import load_dotenv
from kokoro_onnx import Kokoro
from parakeet_mlx import from_pretrained


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MODEL_PATH = PROJECT_ROOT / "models" / "kokoro-v1.0.onnx"
VOICES_PATH = PROJECT_ROOT / "models" / "voices-v1.0.bin"
PARAKEET_ID = "mlx-community/parakeet-tdt-0.6b-v2"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

STATE_FILE = Path("/tmp/phone-agent-call.json")
TRANSCRIPT_DIR = PROJECT_ROOT / "transcripts"

CAPTURE_SR = 16000

VAD_CHUNK_SEC = 0.1
VAD_SILENCE_THRESHOLD = 0.0015
VAD_TRAILING_SILENCE_SEC = 1.2
VAD_MAX_LISTEN_SEC = 20.0
VAD_MIN_SPEECH_SEC = 0.3
INPUT_GAIN = 8.0

BARGE_IN_SUSTAIN_SEC = 0.20   # sustained voice required to fire barge-in

STATE_POLL_SEC = 0.25


OWNER_NAME = os.environ.get("OWNER_NAME", "Pat")

SYSTEM_PROMPT = f"""You are {OWNER_NAME}'s receptionist, taking a phone call on their behalf.
{OWNER_NAME} isn't available right now. Your job is to find out who's calling and what they need, then politely take a message.

Rules:
- You are NOT {OWNER_NAME}. If asked, say you're their assistant.
- Keep responses short and conversational — one or two sentences at a time. No lists, no markdown.
- Speak the way you would on a real phone call: warm, brief, easy to interrupt.
- If the caller wants something time-sensitive, note it; you can't reach {OWNER_NAME} in real-time but you'll relay the message.
- When you have what you need (name, reason, callback number if relevant), wrap up politely and say goodbye.
- If the caller is hostile or wasting time, end the call politely.
"""

GREETING = (
    f"Hello, this is {OWNER_NAME}'s assistant. "
    f"{OWNER_NAME} isn't available right now. May I ask who's calling, and what this is about?"
)

SENTENCE_BOUNDARY = re.compile(r"^(.+?[.!?])\s+", re.DOTALL)


# ---- state file ----

def call_active() -> bool:
    return STATE_FILE.exists()


def read_call_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---- device resolution ----

@dataclass
class Devices:
    input_idx: int
    input_name: str
    output_idx: int
    output_name: str


def resolve_devices(input_hint: str, output_hint: str) -> Devices:
    all_devs = sd.query_devices()

    def find(hint: str, kind: str) -> tuple[int, str]:
        want_in = kind == "input"
        for i, d in enumerate(all_devs):
            ch = d["max_input_channels"] if want_in else d["max_output_channels"]
            if ch > 0 and hint.lower() in d["name"].lower():
                return i, d["name"]
        options = [d["name"] for d in all_devs
                  if (d["max_input_channels"] if want_in else d["max_output_channels"]) > 0]
        raise SystemExit(f"No {kind} device matching {hint!r}. Options: {options}")

    in_idx, in_name = find(input_hint, "input")
    out_idx, out_name = find(output_hint, "output")
    return Devices(in_idx, in_name, out_idx, out_name)


# ---- mic monitor (single shared input stream) ----

class MicMonitor:
    """One InputStream open for the lifetime of a call. Callback fans chunks
    out to multiple subscriber queues — so a barge-in watcher and a listener
    can both see every chunk without competing for them."""

    def __init__(self, input_idx: int) -> None:
        self.input_idx = input_idx
        self.chunk_frames = int(CAPTURE_SR * VAD_CHUNK_SEC)
        self._consumers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def _cb(self, indata, frames, time_info, status) -> None:
        mono = indata[:, 0].copy()
        boosted = np.clip(mono * INPUT_GAIN, -1.0, 1.0)
        with self._lock:
            consumers = list(self._consumers)
        for q in consumers:
            q.put(boosted)

    def start(self) -> None:
        self._stream = sd.InputStream(
            samplerate=CAPTURE_SR, channels=1, device=self.input_idx,
            blocksize=self.chunk_frames, dtype="float32", callback=self._cb,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._consumers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._consumers.remove(q)
            except ValueError:
                pass


def drain_queue(q: queue.Queue) -> int:
    n = 0
    while True:
        try:
            q.get_nowait()
            n += 1
        except queue.Empty:
            return n


def listen(q: queue.Queue) -> np.ndarray | None:
    """VAD-bounded record from a mic subscriber queue. Returns mono float32
    audio at CAPTURE_SR, or None on no-speech / call-ended / timeout. Trims
    leading silence — only chunks from the first detected speech onward are
    kept."""
    speech_started = False
    speech_dur = 0.0
    trailing_silence = 0.0
    chunks: list[np.ndarray] = []
    started_at = time.monotonic()

    while time.monotonic() - started_at < VAD_MAX_LISTEN_SEC:
        if not call_active():
            return None
        try:
            chunk = q.get(timeout=0.2)
        except queue.Empty:
            continue

        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if rms > VAD_SILENCE_THRESHOLD:
            if not speech_started:
                speech_started = True
                print(f"  [vad] speech started rms={rms:.4f}")
            chunks.append(chunk)
            speech_dur += VAD_CHUNK_SEC
            trailing_silence = 0.0
        elif speech_started:
            chunks.append(chunk)
            trailing_silence += VAD_CHUNK_SEC
            if trailing_silence >= VAD_TRAILING_SILENCE_SEC:
                if speech_dur >= VAD_MIN_SPEECH_SEC:
                    break
                speech_started = False
                speech_dur = 0.0
                trailing_silence = 0.0
                chunks = []
                print("  [vad] discarded short noise; still listening")
        # else: pre-speech silence, drop on the floor

    if not speech_started:
        return None
    return np.concatenate(chunks)


# ---- barge-in watcher ----

class BargeInWatcher:
    """Background thread that monitors a private mic subscription for sustained
    caller speech. Fires `on_speech` once when sustained voice exceeds threshold,
    but only if `is_armed()` says we're still in a speak phase the caller could
    actually be interrupting (i.e. player has queued or currently-playing audio).
    Voice activity *after* the agent finishes speaking is just normal turn-taking,
    not a barge-in."""

    def __init__(
        self,
        mic: MicMonitor,
        on_speech: Callable[[], None],
        is_armed: Callable[[], bool],
    ) -> None:
        self.mic = mic
        self.q = mic.subscribe()
        self.on_speech = on_speech
        self.is_armed = is_armed
        self._stop = threading.Event()
        self.fired = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        consec = 0.0
        while not self._stop.is_set():
            try:
                chunk = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms > VAD_SILENCE_THRESHOLD:
                consec += VAD_CHUNK_SEC
                if consec >= BARGE_IN_SUSTAIN_SEC:
                    # Only treat as barge-in if the player is still actually
                    # speaking. Otherwise this is the caller taking their turn.
                    if self.is_armed():
                        self.fired.set()
                        try:
                            self.on_speech()
                        except Exception as e:
                            print(f"[barge_in] on_speech error: {e}")
                    return
            else:
                consec = 0.0

    def start(self) -> None:
        self.fired.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        self.mic.unsubscribe(self.q)

    def is_fired(self) -> bool:
        return self.fired.is_set()


# ---- audio player ----

@dataclass
class PlayedSentence:
    text: str
    started: bool       # sd.play() was called → caller heard at least the start
    fully_played: bool  # sd.play() returned without being stopped early


@contextlib.contextmanager
def _suppress_fd_stderr():
    """Suppress C-level writes to stderr (PaMacCore prints from sd.stop)."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def _safe_sd_stop() -> None:
    """sd.stop() quietly. Swallows transition-window CoreAudio chatter."""
    try:
        with _suppress_fd_stderr():
            sd.stop()
    except (sd.PortAudioError, RuntimeError, OSError):
        pass


class AudioPlayer:
    """FIFO player. Tracks per-sentence completion. Supports interrupt that
    aborts the current buffer and drops queued items."""

    def __init__(self, output_idx: int) -> None:
        self.output_idx = output_idx
        self.q: queue.Queue = queue.Queue()
        self._interrupted = False
        self.played: list[PlayedSentence] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            item = self.q.get()
            try:
                if item is None:
                    return
                sentence, samples, sr = item
                if self._interrupted:
                    with self._lock:
                        self.played.append(PlayedSentence(sentence, started=False, fully_played=False))
                    continue
                sd.play(samples, samplerate=sr, device=self.output_idx, blocking=True)
                # sd.play returned — either natural end, or sd.stop() was called
                with self._lock:
                    self.played.append(PlayedSentence(
                        sentence,
                        started=True,
                        fully_played=not self._interrupted,
                    ))
            finally:
                self.q.task_done()

    def reset_turn(self) -> None:
        with self._lock:
            self._interrupted = False
            self.played = []

    def enqueue(self, sentence: str, samples: np.ndarray, sr: int) -> None:
        self.q.put((sentence, samples, sr))

    def wait_drain(self) -> None:
        self.q.join()

    def interrupt(self) -> None:
        self._interrupted = True
        _safe_sd_stop()
        with self.q.mutex:
            dropped = list(self.q.queue)
            self.q.queue.clear()
            self.q.unfinished_tasks -= len(dropped)
            self.q.all_tasks_done.notify_all()
        with self._lock:
            for (sentence, _samples, _sr) in dropped:
                self.played.append(PlayedSentence(sentence, started=False, fully_played=False))

    def is_interrupted(self) -> bool:
        return self._interrupted

    def is_busy(self) -> bool:
        """True while sentences are queued OR currently in sd.play()."""
        return self.q.unfinished_tasks > 0

    def spoken_text(self) -> str:
        """Text the caller heard at least the beginning of — used for Haiku
        history. Includes sentences that were cut off mid-playback."""
        with self._lock:
            return " ".join(p.text for p in self.played if p.started).strip()

    def shutdown(self) -> None:
        self.q.put(None)


# ---- synth ----

class Synth:
    def __init__(self) -> None:
        print(f"[init] loading Kokoro …")
        t0 = time.monotonic()
        self.kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        print(f"[init] Kokoro loaded in {time.monotonic() - t0:.2f}s")

    def synth_one(self, text: str) -> tuple[np.ndarray, int]:
        samples, sr = self.kokoro.create(text, voice="af_heart", speed=1.0, lang="en-us")
        return np.asarray(samples, dtype=np.float32), sr

    def speak_sync(self, text: str, output_idx: int) -> None:
        samples, sr = self.synth_one(text)
        sd.play(samples, samplerate=sr, device=output_idx, blocking=True)

    def stream_to_player(
        self,
        deltas: Iterable[str],
        player: AudioPlayer,
        on_sentence: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[str, float | None]:
        """Consume `deltas`, synth at every sentence boundary, enqueue to player.
        Aborts streaming if should_stop() returns True. Returns (full_received_text, ttft)."""
        buffer = ""
        full = ""
        first_enqueue_at: float | None = None
        t0 = time.monotonic()

        def emit(sentence: str) -> None:
            nonlocal first_enqueue_at
            s = sentence.strip()
            if not s:
                return
            samples, sr = self.synth_one(s)
            if should_stop and should_stop():
                return
            player.enqueue(s, samples, sr)
            if first_enqueue_at is None:
                first_enqueue_at = time.monotonic() - t0
            if on_sentence:
                on_sentence(s)

        for delta in deltas:
            if should_stop and should_stop():
                break
            buffer += delta
            full += delta
            while True:
                m = SENTENCE_BOUNDARY.match(buffer)
                if not m:
                    break
                emit(m.group(1))
                buffer = buffer[m.end():]

        if not (should_stop and should_stop()) and buffer.strip():
            emit(buffer)

        return full, first_enqueue_at


# ---- STT ----

class Recognizer:
    def __init__(self) -> None:
        print(f"[init] loading Parakeet …")
        t0 = time.monotonic()
        self.model = from_pretrained(PARAKEET_ID)
        print(f"[init] Parakeet loaded in {time.monotonic() - t0:.2f}s")

    def transcribe_array(self, audio: np.ndarray, sr: int) -> str:
        tmp = Path("/tmp/agent-listen.wav")
        sf.write(str(tmp), audio, sr)
        result = self.model.transcribe(str(tmp))
        return result.text.strip() if hasattr(result, "text") else str(result).strip()


# ---- LLM ----

@dataclass
class Conversation:
    claude: Anthropic
    history: list[dict] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        # If the previous turn ended without an assistant message (caller barged
        # in before agent said anything), merge into that user message — the
        # Anthropic API requires strict user/assistant alternation.
        if self.history and self.history[-1]["role"] == "user":
            self.history[-1]["content"] += " " + text
        else:
            self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        if text:
            self.history.append({"role": "assistant", "content": text})

    def stream(self, max_tokens: int = 300):
        """Yields text deltas. Caller is responsible for calling add_assistant
        with whatever portion of the reply actually reached the listener."""
        with self.claude.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=self.history,
        ) as stream:
            for delta in stream.text_stream:
                yield delta


# ---- transcripts ----

def sanitize_for_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s.strip()) or "unknown"


def save_transcript(caller: str, started_at: str, turns: list[dict]) -> Path:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H%M%S")
    fname = f"{ts}_{sanitize_for_filename(caller)}.json"
    out = TRANSCRIPT_DIR / fname
    out.write_text(json.dumps({
        "caller": caller,
        "started_at": started_at,
        "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turns": turns,
    }, indent=2, ensure_ascii=False))
    return out


# ---- conversation driver ----

def run_conversation(synth: Synth, recognizer: Recognizer, devices: Devices) -> None:
    state = read_call_state()
    caller = state.get("caller", "unknown")
    started_at = state.get("started_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    turns: list[dict] = []
    convo = Conversation(claude=Anthropic())

    mic = MicMonitor(devices.input_idx)
    mic.start()
    listen_q = mic.subscribe()
    player = AudioPlayer(devices.output_idx)

    try:
        print(f"\n[call] caller={caller!r} started_at={started_at}")
        print(f">> AGENT: {GREETING}")
        synth.speak_sync(GREETING, devices.output_idx)
        turns.append({"role": "agent", "text": GREETING})
        drain_queue(listen_q)  # discard anything captured while greeting was playing

        while call_active():
            print("\n[listening …]")
            audio = listen(listen_q)
            if not call_active():
                break
            if audio is None:
                print("  [no speech in window; listening again]")
                continue

            user_text = recognizer.transcribe_array(audio, CAPTURE_SR)
            print(f"<< CALLER: {user_text!r}")
            if not user_text:
                continue
            turns.append({"role": "caller", "text": user_text})
            convo.add_user(user_text)

            if not call_active():
                break

            # Speak phase with barge-in detection. Armed only while the player
            # has queued or currently-playing audio.
            player.reset_turn()
            barge_in = BargeInWatcher(
                mic,
                on_speech=player.interrupt,
                is_armed=player.is_busy,
            )
            barge_in.start()

            t_turn_start = time.monotonic()
            full_reply, ttft = synth.stream_to_player(
                convo.stream(),
                player,
                on_sentence=lambda s: print(f">> AGENT: {s}"),
                should_stop=player.is_interrupted,
            )
            player.wait_drain()
            barge_in.stop()
            elapsed = time.monotonic() - t_turn_start

            spoken = player.spoken_text()
            interrupted = player.is_interrupted()
            ttft_s = f"{ttft:.2f}s" if ttft is not None else "?"
            tag = " [INTERRUPTED]" if interrupted else ""
            print(f"[turn]{tag} ttft={ttft_s} total={elapsed:.2f}s")

            if interrupted:
                print(f"   spoken: {spoken!r}")
                # Persist only what the caller actually heard.
                convo.add_assistant(spoken)
                turns.append({
                    "role": "agent", "text": spoken,
                    "interrupted": True,
                    "unsaid": full_reply[len(spoken):].strip(),
                })
                # Don't drain — the barge-in audio is in listen_q already,
                # listen() on the next iteration picks it up.
            else:
                convo.add_assistant(full_reply)
                turns.append({"role": "agent", "text": full_reply})
                drain_queue(listen_q)  # discard ambient captured during speak

    finally:
        player.shutdown()
        mic.unsubscribe(listen_q)
        mic.stop()

    transcript_path = save_transcript(caller, started_at, turns)
    print(f"[call] ended. transcript → {transcript_path}")


# ---- main ----

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="BlackHole 16ch", help="input device name substring")
    parser.add_argument("--output", default="BlackHole 2ch", help="output device name substring")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set (check .env)")

    devices = resolve_devices(args.input, args.output)
    print(f"[devices] in=[{devices.input_idx}] {devices.input_name!r}")
    print(f"[devices] out=[{devices.output_idx}] {devices.output_name!r}")
    print(f"[devices] state file: {STATE_FILE}")

    if STATE_FILE.exists():
        print(f"[init] cleaning stale state file: {STATE_FILE}")
        STATE_FILE.unlink()

    synth = Synth()
    recognizer = Recognizer()

    print(f"\n[daemon] ready. waiting for calls. (Ctrl-C to exit)")

    interrupted = {"v": False}
    def _on_sigint(*_):
        interrupted["v"] = True
    signal.signal(signal.SIGINT, _on_sigint)

    try:
        while not interrupted["v"]:
            if call_active():
                run_conversation(synth, recognizer, devices)
                print("[daemon] idle. waiting for next call.")
            else:
                time.sleep(STATE_POLL_SEC)
    finally:
        print("[daemon] bye")


if __name__ == "__main__":
    main()
