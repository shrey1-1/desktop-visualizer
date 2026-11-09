"""The overlay process: transparent visualizer window, tray icon, audio, colours and RGB sync."""

import os
import signal
import sys
import time
from pathlib import Path

import shiboken6

from PySide6.QtCore import (Property, QFileSystemWatcher, QObject, QRect, Qt, QTimer, QUrl, Signal,
                            Slot)
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QOpenGLContext, QRegion, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, launcher
from .audio import AudioCapture
from .colours import ColourEngine, gradient_style_id
from .instance import InstanceServer
from .openrgb import RGBSync
from .track import TrackWatcher
from .visualizer_item import Visualizer, release_qt_objects

PACKAGE = Path(__file__).resolve().parent
COLOUR_TICK_MS = 33


class OverlayApp(QObject):
    """State shared with Overlay.qml, plus everything that reacts to settings changes."""

    level = Signal(float)
    settingsChanged = Signal()
    editingChanged = Signal()
    seedChanged = Signal()
    coloursChanged = Signal()
    resetRequested = Signal()
    rgbStatus = Signal(str)
    frameRateChanged = Signal()
    restartRequested = Signal()
    analysis = Signal("QVariantList", "QVariantList", bool)  # bands, waveform, beat

    def __init__(self, layer_shell, gpu, parent=None):
        super().__init__(parent)
        self.layer_shell = layer_shell
        self.gpu = gpu  # "dedicated" or "integrated", fixed for the life of the process
        self.has_dedicated = launcher.dedicated_gpu_env() is not None
        self._settings = config.load()
        self._editing = False
        self._seed = 0
        self._colours = [0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0]
        self.window = None
        self.input_rect = QRect()
        self.started = time.monotonic()

        self.engine = ColourEngine(self._settings)
        self.audio = AudioCapture(self.level.emit, on_analysis=self.analysis.emit, **self._audio_options())
        self.audio.analysis_enabled = self._settings["style"] != "sphere"
        self.rgb = RGBSync(on_status=self.rgbStatus.emit)
        self.rgb.configure(self._settings)
        self.tracks = TrackWatcher(player=self._player())
        self.tracks.trackChanged.connect(self._on_track)
        self.tracks.albumColour.connect(self._on_album_colour)
        self.rgbStatus.connect(lambda text: print(f"desktop-visualizer: {text}", file=sys.stderr))

        self.colour_timer = QTimer(self, interval=COLOUR_TICK_MS, timeout=self._tick_colours)
        # In "auto" GPU mode, switch cards when the laptop is plugged in or unplugged.
        self.power_timer = QTimer(self, interval=10000, timeout=self._check_gpu)

        # The settings window writes the config file; reload it whenever it changes.
        # Watch the folder too, because saving replaces the file.
        path = config.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.watcher = QFileSystemWatcher([str(path.parent)], self)
        self.watcher.directoryChanged.connect(self._schedule_reload)
        self.watcher.fileChanged.connect(self._schedule_reload)
        self.reload_timer = QTimer(self, singleShot=True, interval=100, timeout=self.reload)
        self._watch_file()

    # ---- lifecycle ----

    def start(self):
        self.audio.start()
        if os.environ.get("DESKTOP_VISUALIZER_DEMO") == "1":
            # Troubleshooting/benchmark switch: animate with a synthetic song instead of audio.
            from .demo import DemoSong
            song = DemoSong()

            def demo_step():
                level, bands, wave, beat = song.step()
                self.level.emit(level)
                if self._settings["style"] != "sphere":
                    self.analysis.emit(bands, wave, beat)

            self.demo_timer = QTimer(self, interval=20, timeout=demo_step)
            self.demo_timer.start()
        self.rgb.start()
        self.tracks.start()
        self.colour_timer.start()
        self.power_timer.start()
        self._tick_colours()

    def stop(self):
        self.audio.stop()
        self.rgb.stop()

    def attach(self, window):
        self.window = window
        self._apply_input()
        window.screenChanged.connect(lambda *_: self.frameRateChanged.emit())
        self.frameRateChanged.emit()

    # ---- properties for QML ----

    def _get_settings(self):
        return self._settings

    settings = Property("QVariantMap", _get_settings, notify=settingsChanged)

    def _get_editing(self):
        return self._editing

    editing = Property(bool, _get_editing, notify=editingChanged)

    def _get_seed(self):
        return self._seed

    seed = Property(int, _get_seed, notify=seedChanged)

    def _get_colours(self):
        return self._colours

    colours = Property("QVariantList", _get_colours, notify=coloursChanged)

    def _get_frame_rate(self):
        """Frame-rate limit for the renderer; 0 = draw on every display refresh."""
        return self._settings["frame_rate"]

    frameRate = Property(int, _get_frame_rate, notify=frameRateChanged)

    # ---- settings ----

    def _audio_options(self):
        s = self._settings
        return {"source": s["audio_source"], "gain": None if s["auto_gain"] else s["gain"]}

    def _player(self):
        return "spotify" if self._settings["audio_source"] == "spotify" else None

    def _watch_file(self):
        path = str(config.config_path())
        if Path(path).exists() and path not in self.watcher.files():
            self.watcher.addPath(path)

    def _schedule_reload(self, *_):
        self.reload_timer.start()

    def reload(self):
        self._watch_file()
        new = config.load()
        if new == self._settings:
            return
        self._settings = new
        self.audio.configure(**self._audio_options())
        self.audio.analysis_enabled = new["style"] != "sphere"  # the sphere only needs the level
        self.tracks.set_player(self._player())
        self.engine.apply_settings(new, now=self._now())
        self.rgb.configure(new)
        self.settingsChanged.emit()
        self.frameRateChanged.emit()
        self._tick_colours()
        self._check_gpu()

    def _check_gpu(self):
        wanted = launcher.choose_gpu(self._settings["gpu"], self.has_dedicated, launcher.on_ac_power())
        if wanted != self.gpu:
            # The graphics card can only be chosen when the process starts.
            self.restartRequested.emit()

    # ---- colours ----

    def _now(self):
        return time.monotonic() - self.started

    def _on_track(self, seed):
        self._seed = seed
        self.seedChanged.emit()
        self.engine.on_track(None, now=self._now())

    def _on_album_colour(self, r, g, b):
        self.engine.on_track((r, g, b), now=self._now())

    def _tick_colours(self):
        primary, secondary = self.engine.tick(self._now())
        colours = [round(c, 4) for c in (*primary, *secondary)] + [gradient_style_id(self._settings)]
        if colours != self._colours:
            self._colours = colours
            self.coloursChanged.emit()
            self.rgb.set_colour(tuple(colours[:3]))

    # ---- edit mode ----

    @Slot(bool)
    def setEditing(self, editing):
        if editing == self._editing:
            return
        self._editing = editing
        self._apply_input()
        self.editingChanged.emit()

    @Slot()
    def toggleEditing(self):
        self.setEditing(not self._editing)

    @Slot(int, int, int)
    def setInputArea(self, x, y, size):
        self.input_rect = QRect(x, y, size, size)
        if self._editing and self.window is not None:
            self.window.setMask(QRegion(self.input_rect))

    @Slot(int, int, int)
    def saveGeometry(self, x, y, size):
        try:
            self._settings = config.update({"x": x, "y": y, "size": size})
        except (OSError, ValueError) as err:
            print(f"desktop-visualizer: could not save position: {err}", file=sys.stderr)

    def _apply_input(self):
        if self.window is None:
            return
        # Outside edit mode nothing takes input, so clicks reach the windows below.
        self.window.setFlag(Qt.WindowType.WindowTransparentForInput, not self._editing)
        self.window.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not self._editing)
        if self._editing and not self.input_rect.isEmpty():
            self.window.setMask(QRegion(self.input_rect))
        if self._editing:
            self.window.requestActivate()

    # ---- commands from later launches and the tray ----

    def handle_command(self, command):
        if command == "quit":
            QApplication.quit()
        elif command == "edit":
            self.setEditing(True)
        elif command == "centre":
            self.resetRequested.emit()
        elif command == "settings":
            launcher.spawn(["--settings"])


def make_tray(app, overlay):
    icon_file = PACKAGE / "data" / "desktop-visualizer.svg"
    icon = QIcon(str(icon_file)) if icon_file.exists() else QIcon.fromTheme("audio-x-generic")
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Desktop Visualizer")

    menu = QMenu()
    settings = QAction("Settings…", menu)
    settings.triggered.connect(lambda: overlay.handle_command("settings"))
    edit = QAction("Move / resize", menu, checkable=True)
    edit.triggered.connect(overlay.setEditing)
    overlay.editingChanged.connect(lambda: edit.setChecked(overlay.editing))
    centre = QAction("Centre on screen", menu)
    centre.triggered.connect(overlay.resetRequested)
    quit_ = QAction("Quit", menu)
    quit_.triggered.connect(app.quit)
    menu.addActions([settings, edit, centre])
    menu.addSeparator()
    menu.addAction(quit_)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.toggleEditing() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray._menu = menu  # keep the menu alive as long as the tray
    tray.show()
    return tray


def apply_stacking(window, layer):
    """Without layer-shell: always-on-top, or always-below for "Desktop only"."""
    below = layer == "bottom"
    if window.flags() & Qt.WindowType.WindowStaysOnBottomHint and below:
        return
    if window.flags() & Qt.WindowType.WindowStaysOnTopHint and not below:
        return
    visible = window.isVisible()
    window.setFlag(Qt.WindowType.WindowStaysOnTopHint, not below)
    window.setFlag(Qt.WindowType.WindowStaysOnBottomHint, below)
    if visible:  # X11 window managers only read these hints when the window is mapped
        window.hide()
        window.show()


def use_opengl():
    """The visualizer draws with OpenGL, so Qt Quick must use it too (not Vulkan)."""
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    fmt = QSurfaceFormat()
    # Ask for no particular version: EGL on Wayland can refuse an explicit core-profile
    # request, while the default context is the newest compatibility one (4.x on current
    # drivers), which runs the "#version 330 core" shaders. gl_pipeline checks the version.
    if QOpenGLContext.openGLModuleType() != QOpenGLContext.OpenGLModuleType.LibGL:
        fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGLES)
        fmt.setVersion(3, 0)
    fmt.setAlphaBufferSize(8)  # transparent window
    QSurfaceFormat.setDefaultFormat(fmt)


def run(edit=False):
    layer_shell = launcher.configure_platform()
    gpu = launcher.configure_gpu(config.load())

    use_opengl()
    qmlRegisterType(Visualizer, "DesktopVisualizer", 1, 0, "Visualizer")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("desktop-visualizer")
    app.setApplicationDisplayName("Desktop Visualizer")
    app.setDesktopFileName("desktop-visualizer")
    app.setQuitOnLastWindowClosed(False)

    server = InstanceServer("overlay")
    if not server.listening:
        print("desktop-visualizer: already running", file=sys.stderr)
        return 0
    overlay = OverlayApp(layer_shell, gpu)

    restarting = []

    def restart():
        if restarting:
            return
        restarting.append(True)
        server.server.close()  # free the single-instance name for the new process
        launcher.spawn(["--foreground"])
        app.quit()

    overlay.restartRequested.connect(restart)
    server.command.connect(overlay.handle_command)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("app", overlay)
    qml = "OverlayLayerShell.qml" if layer_shell else "Overlay.qml"
    engine.load(QUrl.fromLocalFile(str(PACKAGE / "qml" / qml)))
    if not engine.rootObjects():
        print("desktop-visualizer: failed to load the overlay window", file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]

    if not layer_shell:
        # No layer-shell (GNOME, X11): a taskbar-less window over the screen, kept above
        # or below other windows by the window manager.
        window.setFlag(Qt.WindowType.Tool, True)
        apply_stacking(window, overlay.settings["layer"])
        screen = QGuiApplication.primaryScreen()
        window.setGeometry(screen.availableGeometry())
        overlay.settingsChanged.connect(lambda: apply_stacking(window, overlay.settings["layer"]))

    window.show()
    overlay.attach(window)
    overlay.start()
    app.aboutToQuit.connect(overlay.stop)

    tray = make_tray(app, overlay)  # noqa: F841 (must stay referenced)
    if edit:
        QTimer.singleShot(500, lambda: overlay.setEditing(True))

    # Let Ctrl+C and `kill` close the app cleanly (Python only sees signals between Qt events).
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    tick = QTimer(interval=250, timeout=lambda: None)
    tick.start()

    code = app.exec()
    # Destroy the window (and with it Qt's renderer objects) before Python cleans up.
    del window
    shiboken6.delete(engine)
    release_qt_objects()
    return code


if __name__ == "__main__":
    sys.exit(run("--edit" in sys.argv))
