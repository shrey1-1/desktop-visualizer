"""Follow the current track through MPRIS (playerctl) and derive a seed and album colour."""

import colorsys
import os
import shutil
import tempfile
import zlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

POLL_MS = 1500
MAX_ART_BYTES = 5 * 1024 * 1024
ART_TIMEOUT_MS = 10000
# Cover art is only fetched from Spotify's image CDN. Other players (browsers) hand
# over local temp files. Anything else is ignored, because in "all system audio" mode
# any web page with a media session can choose this URL.
ART_HOSTS = ("i.scdn.co",)


def _art_dirs():
    dirs = [tempfile.gettempdir(), os.environ.get("XDG_RUNTIME_DIR"),
            os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")]
    return [Path(d).resolve() for d in dirs if d]


def art_source(url, art_dirs=None):
    """Return ("https", url) or ("file", path) if the cover may be loaded, else None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme == "https" and (parts.hostname or "").lower() in ART_HOSTS:
        return ("https", url)
    if parts.scheme == "file" and parts.netloc in ("", "localhost"):
        path = Path(unquote(parts.path)).resolve()
        allowed = art_dirs if art_dirs is not None else _art_dirs()
        if any(path.is_relative_to(d) for d in allowed) and path.is_file() \
                and path.stat().st_size <= MAX_ART_BYTES:
            return ("file", str(path))
    return None


def track_seed(track_id):
    """Stable per-track seed for the noise (the original uses the analysis timestamp)."""
    return zlib.crc32(track_id.encode()) & 0x7FFFFFFF


def pick_colour(pixels):
    """Pick a vivid colour from (r, g, b) tuples in 0..255, or None if there are none.

    Pixels are weighted by saturation and brightness so the result follows the
    cover's main colour rather than a muddy average. It is then lifted to a
    bright value because the overlay draws on top of other windows.
    """
    total = r_sum = g_sum = b_sum = 0.0
    for r, g, b in pixels:
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        weight = (s * v) ** 2 + 1e-4
        total += weight
        r_sum += r * weight
        g_sum += g * weight
        b_sum += b * weight
    if total == 0:
        return None
    h, s, v = colorsys.rgb_to_hsv(r_sum / total / 255, g_sum / total / 255, b_sum / total / 255)
    return colorsys.hsv_to_rgb(h, min(s * 1.2, 1.0), max(v, 0.9))


class TrackWatcher(QObject):
    """trackChanged(seed) when the song changes; albumColour(r, g, b) once its cover is analysed."""

    trackChanged = Signal(int)
    albumColour = Signal(float, float, float)

    def __init__(self, player="spotify", parent=None):
        super().__init__(parent)
        self.player = player  # None = whichever player playerctl considers active
        self.track_id = None
        self.network = QNetworkAccessManager(self)
        self.timer = QTimer(self, interval=POLL_MS, timeout=self._poll)
        self.proc = None
        self.available = shutil.which("playerctl") is not None

    def start(self):
        if not self.available:
            return
        self.timer.start()
        self._poll()

    def set_player(self, player):
        if player != self.player:
            self.player = player
            self.track_id = None

    def _poll(self):
        if self.proc is not None:
            return
        self.proc = QProcess(self)
        self.proc.finished.connect(self._on_metadata)
        args = ["-p", self.player] if self.player else []
        self.proc.start("playerctl", args + ["metadata", "--format", "{{mpris:trackid}}\t{{mpris:artUrl}}"])

    def _on_metadata(self):
        out = bytes(self.proc.readAllStandardOutput()).decode(errors="replace").strip()
        self.proc.deleteLater()
        self.proc = None
        if "\t" not in out:
            return
        track_id, art_url = out.split("\t", 1)
        if not track_id or track_id == self.track_id:
            return
        self.track_id = track_id
        self.trackChanged.emit(track_seed(track_id))
        source = art_source(art_url)
        if source is None:
            return
        kind, location = source
        if kind == "file":
            self._use_art(QImage(location), track_id)
            return
        request = QNetworkRequest(QUrl(location))
        request.setTransferTimeout(ART_TIMEOUT_MS)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        reply = self.network.get(request)
        # Stop oversized downloads early instead of buffering them.
        reply.downloadProgress.connect(
            lambda received, _total: reply.abort() if received > MAX_ART_BYTES else None)
        reply.finished.connect(lambda: self._on_art(reply, track_id))

    def _on_art(self, reply, track_id):
        ok = reply.error() == reply.NetworkError.NoError
        data = reply.readAll() if ok else b""
        reply.deleteLater()
        if ok and track_id == self.track_id:
            self._use_art(QImage.fromData(data), track_id)

    def _use_art(self, image, track_id):
        if track_id != self.track_id:
            return
        if image.isNull():
            return
        small = image.scaled(32, 32)
        pixels = [QColor(small.pixel(x, y)).getRgb()[:3] for y in range(32) for x in range(32)]
        colour = pick_colour(pixels)
        if colour is not None:
            self.albumColour.emit(*colour)
