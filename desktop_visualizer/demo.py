"""A synthetic song for DESKTOP_VISUALIZER_DEMO=1: chords, a kick on every beat and hi-hats.

Lets the visualizer (every style) be tried or benchmarked without any music playing.
"""

import numpy as np

from .analysis import Analyzer
from .audio import HOP_SECONDS, SAMPLE_RATE, LevelMeter


class DemoSong:
    BPM = 124

    def __init__(self):
        self.t = 0.0
        self.meter = LevelMeter()
        self.analyzer = Analyzer(SAMPLE_RATE, HOP_SECONDS)
        self.rng = np.random.default_rng(1)

    def next_chunk(self):
        n = int(SAMPLE_RATE * HOP_SECONDS)
        t = self.t + np.arange(n) / SAMPLE_RATE
        self.t += n / SAMPLE_RATE
        beat = 60.0 / self.BPM
        since_kick = t % beat
        kick = np.sin(2 * np.pi * (50 + 90 * np.exp(-since_kick * 30)) * since_kick) * np.exp(-since_kick * 9)
        bar = int(self.t / (beat * 4)) % 4
        root = (110.0, 87.3, 130.8, 98.0)[bar]
        swell = 0.6 + 0.4 * np.sin(2 * np.pi * t / (beat * 8))
        chord = sum(np.sin(2 * np.pi * root * m * t) for m in (1, 1.26, 1.5, 2, 3)) * 0.12 * swell
        since_hat = (t + beat / 2) % (beat / 2)
        hat = self.rng.standard_normal(n) * np.exp(-since_hat * 60) * 0.15
        return (0.9 * kick + chord + hat).astype(np.float32)

    def step(self):
        """(level, bands, wave, beat) for the next 20 ms."""
        samples = self.next_chunk()
        level = self.meter.feed(samples)
        bands, wave, beat = self.analyzer.feed(samples)
        return level, bands.tolist(), wave.tolist(), bool(beat)
