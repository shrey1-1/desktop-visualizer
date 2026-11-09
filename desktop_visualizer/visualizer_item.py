"""Qt Quick item that draws the visualizer with OpenGL (see gl_pipeline.py).

A QML FrameAnimation calls tick() on the GUI thread once per displayed frame, so the
animation follows the display's refresh rate (e.g. 165 Hz). Drawing happens on Qt's
render thread. When nothing is playing, the item fades out and `running` turns off, which
stops the FrameAnimation, so it costs nothing at idle.
"""

import math
import os
import sys
import time

import shiboken6

from PySide6.QtCore import Property, Qt, QTimer, Signal, Slot
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from PySide6.QtQuick import QQuickFramebufferObject, QQuickOpenGLUtils

from .gl_pipeline import FrameState, Pipeline

AMPLITUDE_SMOOTHING = 0.06  # seconds, time constant of the level smoothing
SIGNAL_TIMEOUT = 0.15  # seconds without a level update before treating it as silence
DEFAULT_COLOUR = (0x53 / 255,) * 3

# Objects created in Python but deleted by Qt (the renderer and its framebuffer). Python
# keeps them referenced so it never frees them early; once Qt has deleted them they are
# invalidated so Python doesn't free them a second time. See release_qt_objects().
_qt_owned = []


def _hand_to_qt(obj):
    _qt_owned.append(obj)
    return obj


def release_qt_objects():
    """Call after the windows are destroyed (Qt has deleted everything by then)."""
    while _qt_owned:
        obj = _qt_owned.pop()
        if shiboken6.isValid(obj):
            shiboken6.invalidate(obj)


class Animator:
    """The per-frame maths from the original renderer, fed with live levels. No Qt here."""

    def __init__(self):
        self.level = 0.0
        self.level_time = -math.inf
        self.amplitude = 0.0
        self.time = 0.0  # seconds since the track started
        self.integral = 0.0  # accumulated amplitude over time
        self.silent_for = math.inf
        self.last = None

    def push_level(self, level, now):
        self.level = min(max(level, 0.0), 1.0)
        self.level_time = now
        if self.level > 0.01:
            self.silent_for = 0.0

    def new_track(self):
        self.time = 0.0
        self.integral = 0.0

    def step(self, now):
        dt = 0.0 if self.last is None else min(now - self.last, 0.1)
        self.last = now
        target = 0.0 if now - self.level_time > SIGNAL_TIMEOUT else self.level
        self.amplitude += (target - self.amplitude) * (1 - math.exp(-dt / AMPLITUDE_SMOOTHING))
        self.time += dt
        self.integral += self.amplitude * dt
        if target <= 0.01:
            self.silent_for += dt

    @property
    def noise_offset(self):
        return (0.5 * self.time + self.integral) * 75 * 0.01


class VisualizerRenderer(QQuickFramebufferObject.Renderer):
    def __init__(self):
        super().__init__()
        self.pipeline = None
        self.state = FrameState()
        self.error = None
        self.fbo = None

    def createFramebufferObject(self, size):
        # Qt deletes the previous framebuffer before asking for a new one.
        if self.fbo is not None and shiboken6.isValid(self.fbo):
            shiboken6.invalidate(self.fbo)
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        self.fbo = _hand_to_qt(QOpenGLFramebufferObject(size, fmt))
        return self.fbo

    def synchronize(self, item):
        # Render thread, GUI thread blocked: safe to read the item.
        self.state = item.frame_state()
        item.report_error(self.error)

    def render(self):
        if not self.error:
            try:
                if self.pipeline is None:
                    self.pipeline = Pipeline()
                self.pipeline.render(self.framebufferObject(), self.state)
            except RuntimeError as err:
                self.error = str(err)
                print(f"desktop-visualizer: renderer error: {err}", file=sys.stderr)
            finally:
                # Leave OpenGL the way Qt Quick expects it.
                self.framebufferObject().bind()
                QQuickOpenGLUtils.resetOpenGLState()

    def release_gl(self):
        self.pipeline = None


class Visualizer(QQuickFramebufferObject):
    """QML type `Visualizer`. Fed by the overlay through its slots."""

    shownChanged = Signal()
    runningChanged = Signal()
    errorChanged = Signal()
    frameRateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.anim = Animator()
        self.seed = 0
        self.colours = [*DEFAULT_COLOUR, *DEFAULT_COLOUR, 0]
        self.fade_when_silent = True
        self.fade_delay = 2.0
        self.editing = False
        self.frame_rate = 0  # 0 = every display refresh
        self._shown = False
        self._running = False
        self._error = ""
        self.fps_log = os.environ.get("DESKTOP_VISUALIZER_FPS") == "1"
        self._fps = {"frames": 0, "start": None, "worst": 0.0, "last": None}
        self._renderer = None
        self.windowChanged.connect(self._watch_window)

    # ---- QQuickFramebufferObject ----

    def createRenderer(self):
        self._renderer = _hand_to_qt(VisualizerRenderer())
        return self._renderer

    def _watch_window(self, window):
        if window is not None:
            # Free textures and shaders on the render thread while its OpenGL context is current.
            window.sceneGraphInvalidated.connect(self._release_gl, Qt.ConnectionType.DirectConnection)

    def _release_gl(self):
        if self._renderer is not None and shiboken6.isValid(self._renderer):
            self._renderer.release_gl()

    def frame_state(self):
        c = self.colours
        return FrameState(amplitude=self.anim.amplitude, noise_offset=self.anim.noise_offset, seed=self.seed,
                          colour=tuple(c[0:3]), colour2=tuple(c[3:6]), gradient_style=int(c[6]))

    @Slot()
    def tick(self):
        """One animation step, once per displayed frame (called by a QML FrameAnimation)."""
        if not self._running:
            return
        now = time.monotonic()
        self.anim.step(now)
        if self.fade_when_silent and not self.editing and self.anim.silent_for >= self.fade_delay:
            self._set_shown(False)
            if self.opacity() <= 0.001:
                self._set_running(False)  # faded out: stop until sound returns
                return
        self._log_fps(now)
        self.update()

    def report_error(self, error):
        if error and error != self._error:
            self._error = error
            QTimer.singleShot(0, self.errorChanged.emit)

    # ---- properties for QML ----

    def _get_shown(self):
        return self._shown

    shown = Property(bool, _get_shown, notify=shownChanged)

    def _get_running(self):
        return self._running

    running = Property(bool, _get_running, notify=runningChanged)

    def _get_error(self):
        return self._error

    error = Property(str, _get_error, notify=errorChanged)

    def _get_frame_rate(self):
        return self.frame_rate

    frameRate = Property(int, _get_frame_rate, notify=frameRateChanged)

    # ---- inputs (called from the overlay) ----

    @Slot(float)
    def pushLevel(self, level):
        self.anim.push_level(level, time.monotonic())
        if level > 0.01:
            self._set_shown(True)
            self._start()

    @Slot(int)
    def setTrack(self, seed):
        self.seed = seed
        self.anim.new_track()

    @Slot("QVariantList")
    def setColors(self, colours):
        if len(colours) == 7:
            self.colours = [float(c) for c in colours]
            self.update()

    @Slot(bool, float)
    def setFade(self, enabled, delay):
        self.fade_when_silent = enabled
        self.fade_delay = max(delay, 0.1)
        if not enabled:
            self._set_shown(True)
            self._start()

    @Slot(bool)
    def setEditing(self, editing):
        self.editing = editing
        if editing:
            self._set_shown(True)
            self._start()

    @Slot(int)
    def setFrameRate(self, rate):
        rate = max(0, min(rate, 360))
        if rate != self.frame_rate:
            self.frame_rate = rate
            self.frameRateChanged.emit()

    # ---- frame loop ----

    def _set_shown(self, shown):
        if shown != self._shown:
            self._shown = shown
            self.shownChanged.emit()

    def _set_running(self, running):
        if running != self._running:
            self._running = running
            self.runningChanged.emit()

    def _start(self):
        if not self._running:
            self.anim.last = None
            self._set_running(True)
        self.update()

    def _log_fps(self, now):
        if not self.fps_log:
            return
        f = self._fps
        if f["start"] is None:
            f["start"] = f["last"] = now
            return
        f["frames"] += 1
        f["worst"] = max(f["worst"], now - f["last"])
        f["last"] = now
        if now - f["start"] >= 2.0:
            print(f"desktop-visualizer: fps {f['frames'] / (now - f['start']):.1f} "
                  f"worst-frame {f['worst'] * 1000:.1f}ms", file=sys.stderr, flush=True)
            f.update(frames=0, start=now, worst=0.0)
