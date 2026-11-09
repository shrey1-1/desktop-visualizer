import os
import socket
import tempfile
import unittest
from unittest import mock

from desktop_visualizer import instance
from tests.qt_app import APP


class InstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        name = os.path.join(self.tmp.name, "dv-test")
        patcher = mock.patch.object(instance, "server_name", lambda kind: f"{name}-{kind}")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.servers = []  # keep them alive until the test ends
        self.addCleanup(lambda: [srv.server.close() for srv in self.servers])

    def server(self):
        srv = instance.InstanceServer("overlay")
        self.servers.append(srv)
        return srv

    def pump(self):
        for _ in range(50):
            APP.processEvents()

    def test_second_copy_never_takes_over(self):
        first = self.server()
        second = self.server()
        self.assertTrue(first.listening)
        self.assertFalse(second.listening)

        received = []
        first.command.connect(received.append)
        self.assertTrue(instance.send("overlay", "quit"))
        self.pump()
        self.assertIn("quit", received)

    def test_starts_again_after_the_first_closes(self):
        first = self.server()
        first.server.close()
        self.assertFalse(instance.send("overlay", "ping", timeout_ms=200))
        again = self.server()
        self.assertTrue(again.listening)


    def test_lives_in_private_runtime_dir(self):
        mock.patch.stopall()
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmp.name}):
            self.assertEqual(os.path.dirname(instance.server_name("overlay")), self.tmp.name)

    def test_ignores_a_socket_it_does_not_own(self):
        # Simulate a foreign socket: same path, but our ownership check says no.
        path = instance.server_name("overlay")
        squatter = socket.socket(socket.AF_UNIX)
        squatter.bind(path)
        squatter.listen()
        self.addCleanup(squatter.close)
        with mock.patch.object(instance.os, "getuid", return_value=os.getuid() + 1):
            self.assertFalse(instance.send("overlay", "ping"))


if __name__ == "__main__":
    unittest.main()
