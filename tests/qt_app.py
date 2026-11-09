"""One offscreen Qt application shared by all tests (Qt allows only one per process)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
