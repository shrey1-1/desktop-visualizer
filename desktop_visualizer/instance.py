"""One running copy per user: later launches pass their command to it over a local socket."""

import os
import stat
import tempfile

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name(kind):
    """Full path of the control socket.

    It lives in $XDG_RUNTIME_DIR, which only this user can access, so another account
    can't create the socket first (a plain name would put it in the shared /tmp).
    """
    name = f"desktop-visualizer-{kind}-{os.getuid()}"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and os.path.isdir(runtime):
        return os.path.join(runtime, name)
    return os.path.join(tempfile.gettempdir(), name)


def _trusted(path):
    """Only talk to a socket file owned by this user (matters for the /tmp fallback)."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()


def send(kind, command, timeout_ms=1000):
    """Deliver `command` to the running instance. Returns False if none is running."""
    path = server_name(kind)
    if not _trusted(path):
        return False
    sock = QLocalSocket()
    sock.connectToServer(path)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(command.encode() + b"\n")
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    """Listens for commands from later launches and emits them as `command(str)`."""

    command = Signal(str)

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = server_name(kind)
        # Check first: with UserAccessOption Qt creates the socket elsewhere and moves it
        # into place, so listen() would silently take over a running instance.
        if not send(kind, "ping", timeout_ms=300):
            if not os.path.exists(name) or _trusted(name):
                QLocalServer.removeServer(name)  # a stale socket left by a crash, if any
            self.server.listen(name)  # fails (and we step aside) if someone else owns the path
        # Otherwise another instance is live; callers check `listening` and step aside.
        self.server.newConnection.connect(self._accept)

    @property
    def listening(self):
        return self.server.isListening()

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        while sock.canReadLine():
            text = bytes(sock.readLine()).decode(errors="replace").strip()
            if text:
                self.command.emit(text)
