"""The overlay process: transparent visualizer window, tray icon, audio, colours and RGB sync."""

import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import (Property, QFileSystemWatcher, QObject, QRect, Qt, QTimer, QUrl, Signal,
                            Slot)
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QRegion
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, launcher
from .audio import AudioCapture
from .colours import ColourEngine, gradient_style_id
from .instance import InstanceServer
from .openrgb import RGBSync
from .track import TrackWatcher

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

    def __init__(self, layer_shell, parent=None):
        super().__init__(parent)
        self.layer_shell = layer_shell
        self._settings = config.load()
        self._editing = False
        self._seed = 0
        self._colours = [0.33, 0.33, 0.33, 0.33, 0.33, 0.33, 0]
        self.window = None
        self.input_rect = QRect()
        self.started = time.monotonic()

        self.engine = ColourEngine(self._settings)
        self.audio = AudioCapture(self.level.emit, **self._audio_options())
        self.rgb = RGBSync(on_status=self.rgbStatus.emit)
        self.rgb.configure(self._settings)
        self.tracks = TrackWatcher(player=self._player())
        self.tracks.trackChanged.connect(self._on_track)
        self.tracks.albumColour.connect(self._on_album_colour)
        self.rgbStatus.connect(lambda text: print(f"desktop-visualizer: {text}", file=sys.stderr))

        self.colour_timer = QTimer(self, interval=COLOUR_TICK_MS, timeout=self._tick_colours)

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
        self.rgb.start()
        self.tracks.start()
        self.colour_timer.start()
        self._tick_colours()

    def stop(self):
        self.audio.stop()
        self.rgb.stop()

    def attach(self, window):
        self.window = window
        self._apply_input()

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

    def _get_page_url(self):
        return QUrl.fromLocalFile(str(PACKAGE / "web" / "index.html"))

    pageUrl = Property(QUrl, _get_page_url, constant=True)

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
        self.tracks.set_player(self._player())
        self.engine.apply_settings(new, now=self._now())
        self.rgb.configure(new)
        self.settingsChanged.emit()
        self._tick_colours()

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


def run(edit=False):
    layer_shell = launcher.configure_platform()

    QtWebEngineQuick.initialize()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("desktop-visualizer")
    app.setApplicationDisplayName("Desktop Visualizer")
    app.setDesktopFileName("desktop-visualizer")
    app.setQuitOnLastWindowClosed(False)

    server = InstanceServer("overlay")
    overlay = OverlayApp(layer_shell)
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
        # No layer-shell (GNOME, X11): an always-on-top, taskbar-less window over the screen.
        window.setFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        window.setFlag(Qt.WindowType.Tool, True)
        screen = QGuiApplication.primaryScreen()
        window.setGeometry(screen.availableGeometry())

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

    return app.exec()


if __name__ == "__main__":
    sys.exit(run("--edit" in sys.argv))
