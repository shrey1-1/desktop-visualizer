"""desktop-visualizer command line.

  desktop-visualizer             show the visualizer, or close it if it is already showing
  desktop-visualizer --start     show it (does nothing if already running; used at login)
  desktop-visualizer --quit      close it
  desktop-visualizer --edit      show it in move/resize mode
  desktop-visualizer --settings  open the settings window
"""

import argparse
import sys

from . import __version__


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="desktop-visualizer",
        description="Audio visualizer overlay for the desktop, based on the Spicetify NCS visualizer.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--start", action="store_const", dest="action", const="start",
                        help="show the visualizer if it isn't running")
    action.add_argument("--quit", action="store_const", dest="action", const="quit", help="close the visualizer")
    action.add_argument("--edit", action="store_const", dest="action", const="edit",
                        help="show the visualizer in move/resize mode")
    action.add_argument("--settings", action="store_const", dest="action", const="settings",
                        help="open the settings window")
    parser.add_argument("--foreground", action="store_true",
                        help="run the visualizer in this terminal instead of in the background (for debugging)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)
    args.action = args.action or "toggle"
    return args


def wait_until_closed(instance, timeout=8.0):
    """Block until the overlay has really exited, so a following --start isn't mistaken for 'already running'."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and instance.send("overlay", "ping", timeout_ms=200):
        time.sleep(0.1)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.action == "settings":
        from .settings_window import run
        return run()

    if args.foreground:
        from .overlay import run
        return run(edit=args.action == "edit")

    from PySide6.QtCore import QCoreApplication

    from . import instance, launcher

    QCoreApplication(sys.argv[:1])
    running_command = {"toggle": "quit", "quit": "quit", "edit": "edit", "start": None}[args.action]
    if running_command is None:
        if instance.send("overlay", "ping"):
            return 0
    elif instance.send("overlay", running_command):
        if running_command == "quit":
            wait_until_closed(instance)
        return 0

    if args.action == "quit":
        return 0
    launcher.spawn(["--foreground"] + (["--edit"] if args.action == "edit" else []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
