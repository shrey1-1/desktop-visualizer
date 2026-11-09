"""Capture Spotify's (or all) audio from PipeWire/PulseAudio and turn it into levels."""

import json
import math
import select
import subprocess
import threading
import time

import numpy as np

SAMPLE_RATE = 48000
HOP_SECONDS = 0.02  # how often a level is reported
WINDOW_SECONDS = 0.12  # RMS window, close to the original's 0.15 s moving average
RESCAN_SECONDS = 2.0  # how often to look for Spotify's stream again


def find_spotify_stream(sink_inputs):
    """Pick the index of Spotify's music stream from `pactl -f json list sink-inputs` output.

    Spotify can own more than one stream (Spicetify's web audio shows up as "Chromium"),
    so the stream named "Spotify" is preferred, and a playing stream beats a paused one.
    """
    best, best_rank = None, None
    for stream in sink_inputs:
        props = stream.get("properties", {})
        name = (props.get("application.name") or "").lower()
        binary = (props.get("application.process.binary") or "").lower()
        if name != "spotify" and binary != "spotify":
            continue
        rank = (name == "spotify", not stream.get("corked", False))
        if best_rank is None or rank > best_rank:
            best, best_rank = stream["index"], rank
    return best


def list_sink_inputs():
    try:
        out = subprocess.run(
            ["pactl", "-f", "json", "list", "sink-inputs"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


class LevelMeter:
    """Turns raw samples into a 0..1 level comparable to the original's loudness amplitude.

    With gain=None the level is normalised against a slowly decaying peak, so the
    visual looks the same whatever Spotify's volume slider is set to.
    """

    PEAK_HALF_LIFE = 30.0  # seconds
    TARGET_PEAK = 0.75  # level the recent loudest part maps to
    NOISE_FLOOR = 0.003  # RMS below this is treated as silence

    def __init__(self, gain=None, hop_seconds=HOP_SECONDS, window_seconds=WINDOW_SECONDS):
        self.gain = gain
        self.window = np.zeros(int(SAMPLE_RATE * window_seconds), dtype=np.float32)
        self.peak = 0.0
        self.decay = 0.5 ** (hop_seconds / self.PEAK_HALF_LIFE)

    def feed(self, samples):
        n = len(samples)
        if n >= len(self.window):
            self.window[:] = samples[-len(self.window):]
        else:
            self.window = np.roll(self.window, -n)
            self.window[-n:] = samples
        rms = float(np.sqrt(np.mean(np.square(self.window, dtype=np.float64))))
        if rms < self.NOISE_FLOOR:
            rms = 0.0

        if self.gain is not None:
            return min(rms * self.gain, 1.0)

        self.peak = max(rms, self.peak * self.decay)
        if self.peak <= 0.0:
            return 0.0
        # Keep a minimum reference so very quiet tracks aren't blown up to full size.
        reference = max(self.peak, 0.05)
        return min(self.TARGET_PEAK * rms / reference, 1.0)


class AudioCapture(threading.Thread):
    """Background thread that calls `on_level(level)` every HOP_SECONDS while audio plays.

    source "spotify" records only Spotify's stream; "system" records everything
    playing on the default output.
    """

    def __init__(self, on_level, source="spotify", gain=None):
        super().__init__(daemon=True, name="audio-capture")
        self.on_level = on_level
        self.meter = LevelMeter(gain)
        self.source = source
        self.restart = threading.Event()
        self.stopping = threading.Event()
        self.proc = None

    def configure(self, source, gain):
        """Change source or sensitivity while running (gain=None means automatic)."""
        self.meter.gain = gain
        if source != self.source:
            self.source = source
            self.restart.set()

    def stop(self):
        self.stopping.set()
        self._kill()

    def _kill(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _start_capture(self, target):
        flag = f"--monitor-stream={target}" if self.source == "spotify" else f"--device={target}"
        self.proc = subprocess.Popen(
            [
                "parec", flag, "--format=float32le", f"--rate={SAMPLE_RATE}", "--channels=1",
                "--latency-msec=20", "--client-name=desktop-visualizer",
            ],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def _find_target(self):
        if self.source == "system":
            return "@DEFAULT_MONITOR@"
        return find_spotify_stream(list_sink_inputs())

    def run(self):
        hop_bytes = int(SAMPLE_RATE * HOP_SECONDS) * 4
        target, last_scan, buffer = None, 0.0, b""

        while not self.stopping.is_set():
            now = time.monotonic()
            dead = self.proc is None or self.proc.poll() is not None
            if self.restart.is_set() or dead or now - last_scan >= RESCAN_SECONDS:
                restart = self.restart.is_set()
                self.restart.clear()
                last_scan = now
                found = self._find_target()
                if restart or found != target or dead:
                    self._kill()
                    target, buffer = found, b""
                    if target is not None:
                        try:
                            self._start_capture(target)
                        except OSError:  # parec missing
                            self.proc = None
                            self.stopping.wait(5.0)
                            continue

            proc = self.proc
            if proc is None:
                self.stopping.wait(1.0)
                continue

            # A paused stream sends nothing, so wait with a timeout and rescan meanwhile.
            try:
                ready, _, _ = select.select([proc.stdout], [], [], 0.5)
                chunk = proc.stdout.read1(hop_bytes) if ready else None
            except (OSError, ValueError):  # closed by stop() from another thread
                continue
            if chunk is None:
                continue
            if not chunk:
                self._kill()
                continue
            buffer += chunk
            while len(buffer) >= hop_bytes:
                samples = np.frombuffer(buffer[:hop_bytes], dtype="<f4")
                buffer = buffer[hop_bytes:]
                level = self.meter.feed(samples)
                if math.isfinite(level):
                    try:
                        self.on_level(level)
                    except RuntimeError:  # receiver already destroyed during shutdown
                        self.stopping.set()
                        break

        self._kill()
