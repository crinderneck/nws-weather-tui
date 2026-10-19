#!/usr/bin/env python3
"""
NWS Weather TUI — A short tune generated live from the current conditions.

64 notes on a pentatonic random walk: steps stay small so it reads as a
melody, and every 16th note lands on the root so each phrase resolves.
Samples are synthesized with numpy and streamed as raw PCM to whichever
player is installed (pw-play, paplay or aplay), or, when none is, through
PortAudio with sounddevice (CoreAudio on macOS), looping until muted.
Same weather, same tune.

  * scale  — major pentatonic, minor when it's wet, grey or stormy
  * pitch  — the root rises with the temperature
  * tempo  — notes get shorter as the wind picks up
"""

from __future__ import annotations

import random
import shutil
import subprocess
import threading
import zlib
from typing import Any, List, Optional

import numpy as np

from nws_weather_tui.models import CurrentConditions

RATE = 22050
NOTES = 64
PLAYERS = (
    ["pw-play", "--raw", "--format=s16", f"--rate={RATE}", "--channels=1", "-"],
    ["paplay", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1"],
    ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"],
)
# sounddevice: seconds of audio PortAudio buffers and plays on its own thread,
# so the tune rides out the UI holding the GIL (radar decode, redraws), and
# frames per write, which bounds how long muting waits for the writer.
SD_LATENCY = 0.2
SD_CHUNK = 1024
MAJOR = (0, 2, 4, 7, 9)
MINOR = (0, 3, 5, 7, 10)
GLOOMY = ("rain", "shower", "drizzle", "snow", "storm", "thunder", "fog", "cloudy", "overcast")


def compose(cur: CurrentConditions) -> List[Optional[float]]:
    """Frequencies in Hz (None = rest) for the conditions."""
    temp = cur.temperature_c if cur.temperature_c is not None else 15.0
    desc = (cur.text_description or "").lower()
    rng = random.Random(zlib.crc32(f"{round(temp)}|{desc}".encode()))
    scale = MINOR if any(w in desc for w in GLOOMY) else MAJOR
    root = 57 + int(max(-10.0, min(35.0, temp)) + 10) * 12 // 45  # A3..A4
    deg, notes = 0, []
    for i in range(NOTES):
        if i % 16 == 15:
            deg = 0 if abs(deg) < 3 else 5 * (deg > 0)
        elif i and rng.random() < 0.12:
            notes.append(None)
            continue
        else:
            step = rng.choice((-2, -1, -1, 1, 1, 2))
            deg += step if -5 <= deg + step <= 9 else -step  # bounce off the edges
        midi = root + 12 * (deg // 5) + scale[deg % 5]
        notes.append(440.0 * 2 ** ((midi - 69) / 12))
    return notes


def _sounddevice() -> Any:
    """The sounddevice module, or None if it or its PortAudio library is missing.

    Imported on first use rather than at startup: loading it starts PortAudio,
    and only the tune needs that. It's installed by default on macOS only.
    """
    try:
        import sounddevice
    except (ImportError, OSError):  # OSError: the PortAudio library isn't there
        return None
    return sounddevice


def _tone(freq: Optional[float], dur: float) -> bytes:
    t = np.arange(int(RATE * dur)) / RATE
    if freq is None:
        return np.zeros(len(t), np.int16).tobytes()
    env = np.minimum(t / 0.005, 1.0) * np.exp(-t * 6 / dur)  # 5 ms attack, pluck decay
    wave = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)
    return (wave * env * 0.25 * 32767).astype(np.int16).tobytes()


class Music:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._writer: Optional[threading.Thread] = None  # sounddevice, when no player
        self._stop = threading.Event()

    @staticmethod
    def available() -> bool:
        return any(shutil.which(p[0]) for p in PLAYERS) or _sounddevice() is not None

    @property
    def playing(self) -> bool:
        if self._writer is not None:
            return self._writer.is_alive()
        return self._proc is not None and self._proc.poll() is None

    def play(self, cur: CurrentConditions) -> bool:
        self.stop()
        wind = cur.wind_mps or 0.0
        dur = max(0.12, min(0.3, 0.3 - wind * 0.01))
        # Players first, so Linux plays exactly as before; sounddevice is the
        # macOS path, where none of them exist.
        cmd = next((p for p in PLAYERS if shutil.which(p[0])), None)
        if cmd is None:
            return self._play_sounddevice(compose(cur), dur)
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        self._stop = threading.Event()
        threading.Thread(
            target=self._stream, args=(self._proc, self._stop, compose(cur), dur),
            daemon=True,
        ).start()
        return True

    def _play_sounddevice(self, notes: List[Optional[float]], dur: float) -> bool:
        sd = _sounddevice()
        if sd is None:
            return False
        out = None
        try:
            out = sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16",
                                     latency=SD_LATENCY)
            out.start()
        except sd.PortAudioError:  # no output device, or it refused the format
            if out is not None:
                out.close()
            return False
        self._stop = threading.Event()
        self._writer = threading.Thread(
            target=self._write_loop,
            args=(out, self._stop, b"".join(_tone(f, dur) for f in notes)),
            daemon=True,
        )
        self._writer.start()
        return True

    @staticmethod
    def _write_loop(out: Any, stop: threading.Event, pcm: bytes) -> None:
        """Keep PortAudio's ring buffer full. CoreAudio drains it from C, so
        playback never waits on the GIL; a callback stream does, every ~10 ms,
        and drops audio (clicks) whenever the UI thread holds it longer.

        This thread owns the stream and closes it: aborting a stream while
        another thread is blocked writing to it isn't safe."""
        sd = _sounddevice()
        pos = 0
        try:
            while not stop.is_set():
                chunk = pcm[pos:pos + SD_CHUNK * 2]  # 2 bytes per 16-bit sample
                out.write(chunk)
                pos = (pos + len(chunk)) % len(pcm)
        except sd.PortAudioError:  # e.g. the device was unplugged
            pass
        finally:
            try:
                out.abort()  # drop what's buffered, so muting is immediate
                out.close()
            except sd.PortAudioError:
                pass

    @staticmethod
    def _stream(proc: subprocess.Popen, stop: threading.Event,
                notes: List[Optional[float]], dur: float) -> None:
        tones = [_tone(f, dur) for f in notes]
        try:
            while True:  # loop until muted
                for tone in tones:
                    if stop.is_set():
                        return
                    proc.stdin.write(tone)  # type: ignore[union-attr]
        except (BrokenPipeError, OSError, ValueError):
            pass

    def stop(self) -> None:
        self._stop.set()
        if self._writer is not None:
            self._writer.join(timeout=1.0)  # one chunk, then it closes the stream
            self._writer = None
        if self.playing:
            self._proc.kill()  # type: ignore[union-attr]
            self._proc.wait()  # type: ignore[union-attr]
            try:
                self._proc.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass
        self._proc = None
