"""Frequency bands, waveform and kick-drum detection for the non-sphere styles.

Runs in the audio thread on every 20 ms chunk. Pure numpy, about 15 µs per chunk.
"""

import numpy as np

BAND_COUNT = 64
WAVE_POINTS = 128
FFT_SIZE = 2048
MIN_FREQ = 40.0
MAX_FREQ = 16000.0


def band_edges(sample_rate, fft_size=FFT_SIZE, count=BAND_COUNT, low=MIN_FREQ, high=MAX_FREQ):
    """FFT bin index where each of `count` log-spaced bands starts, plus the final end."""
    freqs = np.geomspace(low, high, count + 1)
    bins = np.round(freqs * fft_size / sample_rate).astype(int)
    # Every band gets at least one bin, so the lowest bands don't collapse into each other.
    for i in range(1, len(bins)):
        bins[i] = max(bins[i], bins[i - 1] + 1)
    return np.clip(bins, 1, fft_size // 2)


class Analyzer:
    """Feed 20 ms chunks; read `bands` (0..1 each), `wave` (-1..1) and `beat` (True on a kick)."""

    PEAK_HALF_LIFE = 4.0  # seconds: how fast the loudness reference adapts
    BEAT_THRESHOLD = 1.45  # bass must jump this far above its recent average
    BEAT_MIN_GAP = 0.18  # seconds between beats
    BEAT_MIN_LEVEL = 0.12  # ignore "beats" in near-silence

    def __init__(self, sample_rate, hop_seconds):
        self.sample_rate = sample_rate
        self.hop = hop_seconds
        self.buffer = np.zeros(FFT_SIZE, dtype=np.float32)
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        self.edges = band_edges(sample_rate)
        # Higher bands span more bins; scale so a flat spectrum doesn't look tilted.
        widths = np.diff(self.edges).astype(np.float32)
        self.band_scale = 1.0 / np.sqrt(widths)
        # Music has much more energy in the bass; tilt up the treble so all bars move.
        self.tilt = np.linspace(1.0, 3.0, BAND_COUNT, dtype=np.float32)
        self.peak = 1e-6
        self.wave_peak = 1e-6
        self.decay = 0.5 ** (hop_seconds / self.PEAK_HALF_LIFE)
        self.bass_average = 0.0
        self.since_beat = 1.0
        self.bands = np.zeros(BAND_COUNT, dtype=np.float32)
        self.wave = np.zeros(WAVE_POINTS, dtype=np.float32)
        self.beat = False

    def feed(self, samples):
        n = len(samples)
        if n >= FFT_SIZE:
            self.buffer[:] = samples[-FFT_SIZE:]
        else:
            self.buffer[:-n] = self.buffer[n:]
            self.buffer[-n:] = samples

        spectrum = np.abs(np.fft.rfft(self.buffer * self.window))
        energy = np.add.reduceat(spectrum, self.edges[:-1])[:BAND_COUNT] * self.band_scale * self.tilt
        self.peak = max(float(energy.max(initial=0.0)), self.peak * self.decay, 1e-6)
        # A gentle curve so quiet bands still show some movement.
        self.bands = np.sqrt(np.clip(energy / self.peak, 0.0, 1.0)).astype(np.float32)

        # Waveform: the newest 1024 samples averaged in groups of 8 (a gentle low-pass, so
        # it reads as a smooth line rather than jagged noise), normalised by a slow peak.
        recent = self.buffer[-WAVE_POINTS * 8:].reshape(WAVE_POINTS, 8).mean(axis=1)
        self.wave_peak = max(float(np.abs(recent).max(initial=0.0)), self.wave_peak * self.decay, 1e-6)
        self.wave = np.clip(recent / self.wave_peak, -1.0, 1.0).astype(np.float32)

        # Kick detection: bass energy jumping above its running average.
        bass = float(self.bands[:6].mean())
        self.since_beat += self.hop
        self.beat = (bass > self.BEAT_MIN_LEVEL and bass > self.bass_average * self.BEAT_THRESHOLD
                     and self.since_beat >= self.BEAT_MIN_GAP)
        if self.beat:
            self.since_beat = 0.0
        self.bass_average += (bass - self.bass_average) * 0.08
        return self.bands, self.wave, self.beat
