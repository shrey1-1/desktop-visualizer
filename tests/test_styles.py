import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.qt_app import APP  # noqa: F401 (creates the Qt application)

from PySide6.QtCore import QSize
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from desktop_visualizer import config
from desktop_visualizer.analysis import BAND_COUNT, WAVE_POINTS, Analyzer, band_edges
from desktop_visualizer.audio import HOP_SECONDS, SAMPLE_RATE
from desktop_visualizer.demo import DemoSong
from desktop_visualizer.gl_pipeline import STYLES, FrameState, Pipeline
from desktop_visualizer.visualizer_item import StyleAnimator

HOP = int(SAMPLE_RATE * HOP_SECONDS)


def tone(freq, seconds, amplitude=0.5):
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def feed(analyzer, samples):
    result = None
    for i in range(0, len(samples) - HOP + 1, HOP):
        result = analyzer.feed(samples[i:i + HOP])
    return result


class AnalyzerTest(unittest.TestCase):
    def test_band_edges_are_increasing_and_in_range(self):
        edges = band_edges(SAMPLE_RATE)
        self.assertEqual(len(edges), BAND_COUNT + 1)
        self.assertTrue(np.all(np.diff(edges) > 0))
        self.assertGreaterEqual(edges[0], 1)

    def test_tone_lights_up_the_matching_band(self):
        for freq, region in ((60, slice(0, 12)), (1000, slice(24, 44)), (8000, slice(48, 64))):
            bands, _, _ = feed(Analyzer(SAMPLE_RATE, HOP_SECONDS), tone(freq, 0.5))
            with self.subTest(freq=freq):
                self.assertIn(int(np.argmax(bands)), range(region.start, region.stop))
                self.assertGreater(float(bands.max()), 0.85)  # near the top of the scale

    def test_silence_is_flat(self):
        bands, wave, beat = feed(Analyzer(SAMPLE_RATE, HOP_SECONDS), np.zeros(SAMPLE_RATE, dtype=np.float32))
        self.assertEqual(float(bands.max()), 0.0)
        self.assertEqual(float(np.abs(wave).max()), 0.0)
        self.assertFalse(beat)

    def test_waveform_shape(self):
        _, wave, _ = feed(Analyzer(SAMPLE_RATE, HOP_SECONDS), tone(100, 0.5))
        self.assertEqual(len(wave), WAVE_POINTS)
        self.assertGreater(float(wave.max()), 0.8)  # normalised to the recent peak
        self.assertLess(float(wave.min()), -0.8)

    def test_kick_drum_beats(self):
        song = DemoSong()
        beats = sum(song.step()[3] for _ in range(int(8 / HOP_SECONDS)))  # 8 seconds at 124 BPM
        self.assertTrue(12 <= beats <= 20, beats)  # about 16 kicks

    def test_steady_tone_is_not_a_beat(self):
        analyzer = Analyzer(SAMPLE_RATE, HOP_SECONDS)
        feed(analyzer, tone(60, 1.0))
        beats = 0
        for _ in range(50):
            beats += analyzer.feed(tone(60, HOP_SECONDS))[2]
        self.assertEqual(beats, 0)


class StyleAnimatorTest(unittest.TestCase):
    def test_bars_rise_fast_and_fall_slowly(self):
        anim = StyleAnimator()
        anim.set_analysis([1.0] * 64, [0.0] * 128, False)
        anim.step(0.05)
        risen = float(anim.bands[0])
        self.assertGreater(risen, 0.8)
        anim.set_analysis([0.0] * 64, [0.0] * 128, False)
        anim.step(0.05)
        self.assertGreater(float(anim.bands[0]), risen * 0.5)  # falls more slowly than it rose

    def test_beats_start_ripples_that_expire(self):
        anim = StyleAnimator()
        anim.set_analysis([0.0] * 64, [0.0] * 128, True)
        self.assertEqual(sum(age >= 0 for age in anim.rings), 1)
        for _ in range(10):
            anim.step(0.05)
        self.assertAlmostEqual(max(anim.rings), 0.5, places=5)
        for _ in range(20):
            anim.step(0.05)
        self.assertTrue(all(age < 0 for age in anim.rings))

    def test_many_beats_reuse_the_oldest_slot(self):
        anim = StyleAnimator()
        for _ in range(12):
            anim.set_analysis([0.0] * 64, [0.0] * 128, True)
            anim.step(0.01)
        self.assertEqual(len(anim.rings), 8)

    def test_ignores_wrong_sizes(self):
        anim = StyleAnimator()
        anim.set_analysis([1.0] * 3, [1.0] * 5, False)
        self.assertEqual(float(anim.target.max()), 0.0)


class StyleSettingTest(unittest.TestCase):
    def test_styles_are_valid_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            self.assertEqual(config.load(path)["style"], "sphere")
            for style in STYLES:
                self.assertEqual(config.update({"style": style}, path)["style"], style)
            with self.assertRaises(ValueError):
                config.update({"style": "lasers"}, path)


class StyleRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = QOpenGLContext()
        if not cls.context.create():
            raise unittest.SkipTest("no OpenGL")
        cls.surface = QOffscreenSurface()
        cls.surface.setFormat(cls.context.format())
        cls.surface.create()
        if not cls.context.makeCurrent(cls.surface):
            raise unittest.SkipTest("no OpenGL")
        try:
            cls.pipeline = Pipeline()
        except RuntimeError as err:
            raise unittest.SkipTest(f"OpenGL too old: {err}")

    @classmethod
    def tearDownClass(cls):
        cls.context.makeCurrent(cls.surface)
        cls.pipeline = None
        cls.context.doneCurrent()

    def draw(self, style, size=200, **state):
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        target = QOpenGLFramebufferObject(QSize(size, size), fmt)
        values = dict(amplitude=0.6, noise_offset=1.0, seed=3, colour=(1, 1, 1), colour2=(1, 1, 1), style=style,
                      bands=tuple([0.7] * 64), wave=tuple(np.sin(np.arange(128) * 0.2).tolist()),
                      rings=(0.2, 0.6, -1, -1, -1, -1, -1, -1))
        values.update(state)
        self.pipeline.render(target, FrameState(**values))
        return target.toImage()

    @staticmethod
    def lit(img):
        return [(x, y) for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
                if img.pixelColor(x, y).alpha() > 40]

    def test_every_style_draws_something_centred(self):
        for style in STYLES:
            with self.subTest(style=style):
                img = self.draw(style)
                lit = self.lit(img)
                self.assertGreater(len(lit), 150)
                cx = sum(x for x, _ in lit) / len(lit)
                self.assertAlmostEqual(cx, 100, delta=15)

    def test_louder_bands_mean_bigger_bars(self):
        for style in ("ring", "bars"):
            with self.subTest(style=style):
                quiet = len(self.lit(self.draw(style, bands=tuple([0.1] * 64))))
                loud = len(self.lit(self.draw(style, bands=tuple([0.9] * 64))))
                self.assertGreater(loud, quiet * 1.3)

    def test_bass_is_at_the_bottom_of_the_ring(self):
        # Only the bass bands are loud: the lit area must sit below the centre.
        bands = tuple([1.0] * 8 + [0.0] * 56)
        lit = self.lit(self.draw("ring", bands=bands))
        far = [(x, y) for x, y in lit if (x - 100) ** 2 + (y - 100) ** 2 > 75 ** 2]
        self.assertTrue(far)
        self.assertGreater(sum(y for _, y in far) / len(far), 100)  # image y grows downwards

    def test_style_colour(self):
        img = self.draw("pulse", colour=(1, 0, 0), colour2=(1, 0, 0))
        c = img.pixelColor(100, 100)
        self.assertGreater(c.red(), 150)
        self.assertLess(c.green() + c.blue(), 20)

    def test_sphere_unchanged_by_style_data(self):
        # The sphere ignores bands/waves/rings entirely.
        a = self.draw("sphere", bands=tuple([0.0] * 64))
        b = self.draw("sphere", bands=tuple([1.0] * 64), wave=tuple([1.0] * 128))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
