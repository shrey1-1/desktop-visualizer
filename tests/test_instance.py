import os
import unittest
from unittest import mock

from desktop_visualizer import instance
from tests.qt_app import APP


class InstanceTest(unittest.TestCase):
    def setUp(self):
        name = f"dv-test-{os.getpid()}-{self.id().rsplit('.', 1)[-1]}"
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


if __name__ == "__main__":
    unittest.main()
