import math
import unittest

from tests.qt_app import APP  # noqa: F401 (creates the Qt application)

from PySide6.QtCore import QSize
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

from desktop_visualizer.gl_pipeline import FrameState, Pipeline, shader_source
from desktop_visualizer.visualizer_item import Animator


class AnimatorTest(unittest.TestCase):
    def test_follows_the_level_smoothly(self):
        a = Animator()
        a.step(0.0)
        a.push_level(0.8, 0.0)
        a.step(0.03)
        self.assertTrue(0.1 < a.amplitude < 0.8)  # moving towards the level, not jumping
        for i in range(2, 40):
            a.push_level(0.8, i * 0.01)
            a.step(i * 0.01)
        self.assertAlmostEqual(a.amplitude, 0.8, places=2)

    def test_silence_when_updates_stop(self):
        a = Animator()
        a.step(0.0)
        a.push_level(0.8, 0.0)
        for i in range(1, 100):
            a.step(i * 0.01)  # no new levels after t=0
        self.assertLess(a.amplitude, 0.01)
        self.assertGreater(a.silent_for, 0.5)

    def test_noise_offset_grows_with_time_and_loudness(self):
        quiet, loud = Animator(), Animator()
        for a, level in ((quiet, 0.1), (loud, 0.9)):
            for i in range(100):
                a.push_level(level, i * 0.02)
                a.step(i * 0.02)
        self.assertGreater(loud.noise_offset, quiet.noise_offset > 0)

    def test_new_track_resets_motion(self):
        a = Animator()
        for i in range(50):
            a.push_level(0.5, i * 0.02)
            a.step(i * 0.02)
        a.new_track()
        self.assertEqual(a.noise_offset, 0.0)

    def test_long_pause_does_not_jump(self):
        a = Animator()
        a.step(0.0)
        a.push_level(0.5, 0.0)
        a.step(30.0)  # e.g. the laptop slept
        self.assertLessEqual(a.time, 0.1)
        self.assertFalse(math.isnan(a.amplitude))


class ShaderSourceTest(unittest.TestCase):
    def test_desktop_drops_precision_lines(self):
        src = shader_source("precision highp float;\nvoid main() {}\n", gles=False)
        self.assertTrue(src.startswith("#version 330 core\n"))
        self.assertNotIn("precision", src)

    def test_gles_keeps_them(self):
        src = shader_source("precision highp float;\nvoid main() {}\n", gles=True)
        self.assertTrue(src.startswith("#version 300 es\n"))
        self.assertIn("precision highp float;", src)


class PipelineTest(unittest.TestCase):
    """Draws real frames offscreen. Skipped where no OpenGL is available (e.g. CI without a GPU)."""

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

    def draw(self, size=160, **state):
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        target = QOpenGLFramebufferObject(QSize(size, size), fmt)
        defaults = dict(amplitude=0.6, noise_offset=1.0, seed=7, colour=(1, 1, 1), colour2=(1, 1, 1))
        self.pipeline.render(target, FrameState(**{**defaults, **state}))
        return target.toImage()

    def lit(self, img):
        return [(x, y) for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
                if img.pixelColor(x, y).alpha() > 40]

    def test_draws_a_sphere_with_a_transparent_background(self):
        img = self.draw()
        lit = self.lit(img)
        self.assertGreater(len(lit), 300)
        self.assertEqual(img.pixelColor(1, 1).alpha(), 0)  # corner stays see-through
        cx = sum(x for x, _ in lit) / len(lit)
        cy = sum(y for _, y in lit) / len(lit)
        self.assertAlmostEqual(cx, 80, delta=12)  # centred
        self.assertAlmostEqual(cy, 80, delta=12)

    def test_same_state_same_picture(self):
        self.assertEqual(self.draw(seed=3), self.draw(seed=3))
        self.assertNotEqual(self.draw(seed=3), self.draw(seed=4))

    def test_louder_means_bigger(self):
        def radius(img):
            return max(abs(x - 80) for x, _ in self.lit(img))
        self.assertGreater(radius(self.draw(amplitude=1.0)), radius(self.draw(amplitude=0.0)))

    def test_colour_and_gradient(self):
        red = self.draw(colour=(1, 0, 0), colour2=(1, 0, 0))
        c = max((red.pixelColor(x, y) for x, y in self.lit(red)), key=lambda c: c.alpha())
        self.assertGreater(c.red(), 200)
        self.assertLess(c.green() + c.blue(), 20)

        grad = self.draw(colour=(1, 0, 0), colour2=(0, 0, 1), gradient_style=1)  # vertical
        top = [grad.pixelColor(x, y) for x, y in self.lit(grad) if y < 50]
        bottom = [grad.pixelColor(x, y) for x, y in self.lit(grad) if y > 110]
        self.assertGreater(sum(p.blue() - p.red() for p in top), 0)  # second colour at the top
        self.assertGreater(sum(p.red() - p.blue() for p in bottom), 0)

    def test_resizing(self):
        for size in (120, 333, 160):
            self.assertGreater(len(self.lit(self.draw(size=size))), 100)


if __name__ == "__main__":
    unittest.main()
