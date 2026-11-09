"""One running copy per user: later launches pass their command to it over a local socket."""

import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name(kind):
    return f"desktop-visualizer-{kind}-{os.getuid()}"


def send(kind, command, timeout_ms=1000):
    """Deliver `command` to the running instance. Returns False if none is running."""
    sock = QLocalSocket()
    sock.connectToServer(server_name(kind))
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
        if not self.server.listen(name):
            # A crashed instance can leave a stale socket file behind.
            QLocalServer.removeServer(name)
            self.server.listen(name)
        self.server.newConnection.connect(self._accept)

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
