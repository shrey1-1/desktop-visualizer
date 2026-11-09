"""The settings window: a separate process that edits the shared config file.

The overlay watches that file and applies changes live, so the two never need to
share a window system setup (the overlay may be a layer-shell surface; this is a
normal window).
"""

import os
import sys
import threading
from pathlib import Path

from . import launcher

# A normal window, even when started from the overlay process.
os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)

from PySide6.QtCore import (Property, QFileSystemWatcher, QLibraryInfo, QObject, QTimer, QUrl, Signal,  # noqa: E402
                            Slot)
from PySide6.QtGui import QGuiApplication, QIcon  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from . import config, instance, openrgb  # noqa: E402
from .colours import PALETTES, PRESETS  # noqa: E402

PACKAGE = Path(__file__).resolve().parent


class SettingsBackend(QObject):
    settingsChanged = Signal()
    autostartChanged = Signal()
    overlayRunningChanged = Signal()
    error = Signal(str)
    openrgbScanned = Signal("QVariantList", "QVariantList", str)  # devices, profiles, error

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = config.load()
        self._autostart = launcher.autostart_enabled()
        self._overlay_running = False

        path = config.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.watcher = QFileSystemWatcher([str(path.parent)], self)
        self.watcher.directoryChanged.connect(lambda *_: self.reload_timer.start())
        self.reload_timer = QTimer(self, singleShot=True, interval=150, timeout=self._reload)

        self.status_timer = QTimer(self, interval=2000, timeout=self._check_overlay)
        self.status_timer.start()
        self._check_overlay()

    # ---- properties ----

    def _get_settings(self):
        return self._settings

    settings = Property("QVariantMap", _get_settings, notify=settingsChanged)

    def _get_defaults(self):
        return config.DEFAULTS

    defaults = Property("QVariantMap", _get_defaults, constant=True)

    def _get_presets(self):
        return [{"name": name, "colour": colour} for name, colour in PRESETS]

    presets = Property("QVariantList", _get_presets, constant=True)

    def _get_palettes(self):
        return [{"id": key, "name": name, "colours": colours} for key, (name, colours) in PALETTES.items()]

    palettes = Property("QVariantList", _get_palettes, constant=True)

    def _get_autostart(self):
        return self._autostart

    autostart = Property(bool, _get_autostart, notify=autostartChanged)

    def _get_overlay_running(self):
        return self._overlay_running

    overlayRunning = Property(bool, _get_overlay_running, notify=overlayRunningChanged)

    # ---- actions ----

    @Slot(str, "QVariant")
    def set(self, key, value):
        if isinstance(value, float) and isinstance(config.DEFAULTS.get(key), int) and value.is_integer():
            value = int(value)
        try:
            self._settings = config.update({key: value})
        except (KeyError, ValueError, OSError) as err:
            self.error.emit(f"Could not save {key}: {err}")
            return
        self.settingsChanged.emit()

    @Slot("QStringList")
    def resetKeys(self, keys):
        try:
            self._settings = config.reset([k for k in keys if k in config.DEFAULTS])
        except OSError as err:
            self.error.emit(f"Could not save: {err}")
            return
        self.settingsChanged.emit()

    @Slot(bool)
    def setAutostart(self, enabled):
        try:
            launcher.set_autostart(enabled)
        except OSError as err:
            self.error.emit(f"Could not change start at login: {err}")
        self._autostart = launcher.autostart_enabled()
        self.autostartChanged.emit()

    @Slot(str)
    def overlay(self, command):
        """Tell the overlay to start, quit, edit (move/resize) or centre."""
        if command == "start":
            if not instance.send("overlay", "ping"):
                launcher.spawn(["--foreground"])
        elif command == "edit":
            if not instance.send("overlay", "edit"):
                launcher.spawn(["--foreground", "--edit"])
        elif command in ("quit", "centre"):
            instance.send("overlay", command)
        QTimer.singleShot(1500, self._check_overlay)

    @Slot()
    def scanOpenRGB(self):
        host, port = self._settings["openrgb_host"], self._settings["openrgb_port"]

        def work():
            try:
                devices, profiles = openrgb.scan(host, port)
                result = ([{"name": n, "leds": leds} for n, leds in devices], profiles, "")
            except (OSError, openrgb.OpenRGBError) as err:
                result = ([], [], f"Couldn't reach OpenRGB at {host}:{port} ({err}). "
                                  "Start OpenRGB and enable its SDK server.")
            self.openrgbScanned.emit(*result)  # queued to the GUI thread

        threading.Thread(target=work, daemon=True).start()

    # ---- internals ----

    def _reload(self):
        new = config.load()
        if new != self._settings:
            self._settings = new
            self.settingsChanged.emit()

    def _check_overlay(self):
        running = instance.send("overlay", "ping", timeout_ms=300)
        if running != self._overlay_running:
            self._overlay_running = running
            self.overlayRunningChanged.emit()


def run():
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("desktop-visualizer-settings")
    app.setApplicationDisplayName("Desktop Visualizer Settings")
    app.setDesktopFileName("desktop-visualizer")
    icon = PACKAGE / "data" / "desktop-visualizer.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # One settings window: a second launch just brings the first one forward.
    if instance.send("settings", "raise"):
        return 0
    server = instance.InstanceServer("settings")

    if not os.environ.get("QT_QUICK_CONTROLS_STYLE"):
        # KDE's style blends in on Plasma; Fusion works everywhere else.
        kde = "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        qml_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
        has_kde_style = (qml_dir / "org" / "kde" / "desktop").is_dir()
        QQuickStyle.setStyle("org.kde.desktop" if kde and has_kde_style else "Fusion")

    backend = SettingsBackend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(PACKAGE / "qml" / "Settings.qml")))
    if not engine.rootObjects():
        print("desktop-visualizer: failed to load the settings window", file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    server.command.connect(lambda _cmd: (window.show(), window.raise_(), window.requestActivate()))
    return app.exec()
