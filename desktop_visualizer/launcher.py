"""Platform choice, starting the other process, and the start-at-login entry."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
# The environment before we changed anything, for starting other processes (the
# settings window must not inherit the overlay's layer-shell setting).
ORIGINAL_ENV = dict(os.environ)


def layer_shell_available():
    """True if Qt's layer-shell plugin and QML module (layer-shell-qt) are installed."""
    from PySide6.QtCore import QLibraryInfo

    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    qml = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    return (plugins / "wayland-shell-integration" / "liblayer-shell.so").exists() and \
        (qml / "org" / "kde" / "layershell").is_dir()


def choose_backend(env=None, has_layer_shell=None):
    """Return "layer-shell" or "x11" for the overlay window.

    Layer-shell needs a Wayland compositor that supports it (KDE Plasma, Hyprland, Sway,
    and other wlroots ones). GNOME doesn't, so it gets an always-on-top X11 window via
    XWayland, as does a plain X11 session. DESKTOP_VISUALIZER_BACKEND overrides the choice.
    """
    env = os.environ if env is None else env
    forced = env.get("DESKTOP_VISUALIZER_BACKEND", "").lower()
    if forced in ("layer-shell", "x11"):
        return forced
    wayland = env.get("XDG_SESSION_TYPE") == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    gnome = "gnome" in env.get("XDG_CURRENT_DESKTOP", "").lower()
    if has_layer_shell is None:
        has_layer_shell = layer_shell_available()
    if wayland and not gnome and has_layer_shell:
        return "layer-shell"
    return "x11"


def configure_platform():
    """Set Qt's platform before QApplication exists. Returns True when using layer-shell."""
    if choose_backend() == "layer-shell":
        os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        return True
    os.environ.pop("QT_WAYLAND_SHELL_INTEGRATION", None)
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    return False


def boot_code(app_dir):
    """Python code that runs the app from `app_dir`.

    Used with `python -I -c`: isolated mode keeps the current folder (and PYTHONPATH)
    off the import path, so a stray desktop_visualizer/ wherever you happen to run
    the command can't shadow the installed one.
    """
    return (f"import sys; sys.path.insert(0, {str(app_dir)!r}); "
            "from desktop_visualizer.__main__ import main; sys.exit(main())")


def module_command(args):
    return [sys.executable, "-I", "-c", boot_code(PACKAGE.parent), *args]


def spawn(args):
    """Start `desktop-visualizer <args>` as a separate, detached process."""
    env = dict(ORIGINAL_ENV)
    log_dir = Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "desktop-visualizer"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "log.txt", "ab") as log:
        subprocess.Popen(module_command(args), env=env, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=log, start_new_session=True)


# ---- start at login ----

def autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "autostart" / "desktop-visualizer.desktop"


def launcher_command():
    """Command that starts the app, for .desktop files (absolute, since PATH may lack ~/.local/bin)."""
    installed = os.environ.get("DESKTOP_VISUALIZER_LAUNCHER")
    if installed and Path(installed).exists():
        return shlex.quote(installed)
    return " ".join(shlex.quote(part) for part in module_command([]))


def autostart_enabled():
    return autostart_path().exists()


def set_autostart(enabled):
    path = autostart_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Desktop Visualizer\n"
        "Comment=Audio visualizer overlay\n"
        f"Exec={launcher_command()} --start\n"
        "Icon=desktop-visualizer\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
