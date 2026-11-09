import socket
import struct
import threading
import time
import unittest

from desktop_visualizer import openrgb


def pstr(text):
    data = text.encode() + b"\0"
    return struct.pack("<H", len(data)) + data


def controller_blob(name, led_count, protocol, matrix=False, segments=1):
    """Encode controller data the way OpenRGB's RGBController::GetDeviceDescription does."""
    body = struct.pack("<i", 5)  # device type: keyboard
    body += pstr(name)
    if protocol >= 1:
        body += pstr("ASUS")
    body += pstr("desc") + pstr("1.0") + pstr("serial") + pstr("HID: /dev/hidraw0")
    modes = [("Direct", 2), ("Static", 1)]
    body += struct.pack("<H", len(modes)) + struct.pack("<i", 0)
    for mode_name, colours in modes:
        body += pstr(mode_name)
        body += struct.pack("<iIII", 0, 0, 0, 0)  # value, flags, speed min, max
        if protocol >= 3:
            body += struct.pack("<II", 0, 100)
        body += struct.pack("<III", 1, 1, 0)  # colours min, max, speed
        if protocol >= 3:
            body += struct.pack("<I", 100)
        body += struct.pack("<II", 0, 1)  # direction, colour mode
        body += struct.pack("<H", colours) + b"\x01\x02\x03\x00" * colours
    zones = [("Keyboard", led_count)]
    body += struct.pack("<H", len(zones))
    for zone_name, count in zones:
        body += pstr(zone_name) + struct.pack("<iIII", 1, count, count, count)
        if matrix:
            h, w = 2, 3
            body += struct.pack("<H", 8 + 4 * h * w) + struct.pack("<II", h, w) + b"\xff\xff\xff\xff" * h * w
        else:
            body += struct.pack("<H", 0)
        if protocol >= 4:
            body += struct.pack("<H", segments)
            for n in range(segments):
                body += pstr(f"seg{n}") + struct.pack("<iII", 0, 0, count)
    body += struct.pack("<H", led_count)
    for n in range(led_count):
        body += pstr(f"Key {n}") + struct.pack("<I", n)
    body += struct.pack("<H", led_count) + b"\0\0\0\0" * led_count
    return struct.pack("<I", len(body) + 4) + body


class FakeOpenRGB(threading.Thread):
    """Speaks enough of the SDK protocol to test the client."""

    def __init__(self, devices, profiles=(), protocol=4, push_notification=False):
        super().__init__(daemon=True)
        self.devices = devices  # [(name, leds)]
        self.profiles = list(profiles)
        self.protocol = protocol
        self.push_notification = push_notification
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.received = []  # (device, packet id, payload)
        self.client_protocol = None
        self.event = threading.Event()

    def recv_exact(self, conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def reply(self, conn, device, packet_id, payload):
        conn.sendall(openrgb.HEADER.pack(b"ORGB", device, packet_id, len(payload)) + payload)

    def run(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        try:
            while True:
                magic, device, packet_id, size = openrgb.HEADER.unpack(self.recv_exact(conn, 16))
                payload = self.recv_exact(conn, size)
                self.received.append((device, packet_id, payload))
                self.event.set()
                if packet_id == openrgb.REQUEST_PROTOCOL_VERSION:
                    self.client_protocol = struct.unpack("<I", payload)[0]
                    self.reply(conn, 0, packet_id, struct.pack("<I", self.protocol))
                elif packet_id == openrgb.REQUEST_CONTROLLER_COUNT:
                    if self.push_notification:  # DEVICE_LIST_UPDATED arriving first
                        self.reply(conn, 0, 100, b"")
                    self.reply(conn, 0, packet_id, struct.pack("<I", len(self.devices)))
                elif packet_id == openrgb.REQUEST_CONTROLLER_DATA:
                    version = min(self.protocol, struct.unpack("<I", payload)[0]) if payload else 0
                    name, leds = self.devices[device]
                    self.reply(conn, device, packet_id, controller_blob(name, leds, version, matrix=device == 0))
                elif packet_id == openrgb.REQUEST_PROFILE_LIST:
                    body = struct.pack("<H", len(self.profiles)) + b"".join(pstr(p) for p in self.profiles)
                    self.reply(conn, 0, packet_id, struct.pack("<I", len(body) + 4) + body)
        except (ConnectionError, OSError):
            conn.close()

    def close(self):
        self.listener.close()

    def packets(self, packet_id):
        return [(d, p) for d, pid, p in self.received if pid == packet_id]

    def wait_for(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False


class ParserTest(unittest.TestCase):
    def test_parses_every_protocol_version(self):
        for protocol in range(5):
            for matrix in (False, True):
                with self.subTest(protocol=protocol, matrix=matrix):
                    blob = controller_blob("ROG Strix Keyboard", 84, protocol, matrix=matrix, segments=2)
                    self.assertEqual(openrgb.parse_controller(blob, protocol), ("ROG Strix Keyboard", 84))

    def test_truncated_data(self):
        # Cut inside the modes, before the LED count the parser needs.
        blob = controller_blob("Keyboard", 10, 4)
        with self.assertRaises(openrgb.OpenRGBError):
            openrgb.parse_controller(blob[:80], 4)

    def test_update_leds_packet(self):
        packet = openrgb.build_update_leds((1.0, 0.5, 0.0), 3)
        size, count = struct.unpack("<IH", packet[:6])
        self.assertEqual((size, count, len(packet)), (6 + 12, 3, 18))
        self.assertEqual(packet[6:10], bytes((255, 128, 0, 0)))


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeOpenRGB([("ROG Strix Keyboard", 84), ("TUF Gaming M3", 2)], profiles=["Normal", "Off"],
                                  protocol=5, push_notification=True)
        self.server.start()

    def tearDown(self):
        self.server.close()

    def test_scan_lists_devices_and_profiles(self):
        devices, profiles = openrgb.scan("127.0.0.1", self.server.port)
        self.assertEqual(devices, [("ROG Strix Keyboard", 84), ("TUF Gaming M3", 2)])
        self.assertEqual(profiles, ["Normal", "Off"])
        # Asks for at most the newest layout it can parse, even if the server is newer.
        self.assertEqual(self.server.client_protocol, openrgb.CLIENT_PROTOCOL)

    def test_sync_sets_selected_devices_and_restores_profile(self):
        sync = openrgb.RGBSync()
        settings = dict(openrgb_enabled=True, openrgb_host="127.0.0.1", openrgb_port=self.server.port,
                        openrgb_devices=["TUF Gaming M3"], openrgb_brightness=0.5,
                        openrgb_restore_profile="Normal")
        sync.configure(settings)
        sync.start()
        sync.set_colour((1.0, 0.0, 1.0))
        self.assertTrue(self.server.wait_for(lambda: self.server.packets(openrgb.RGBCONTROLLER_UPDATELEDS)))
        updates = self.server.packets(openrgb.RGBCONTROLLER_UPDATELEDS)
        self.assertEqual({d for d, _ in updates}, {1})  # only the mouse was selected
        self.assertEqual(updates[-1][1][6:10], bytes((128, 0, 128, 0)))  # 50 % brightness
        self.assertEqual([d for d, _ in self.server.packets(openrgb.RGBCONTROLLER_SETCUSTOMMODE)], [1])

        sync.stop()
        self.assertTrue(self.server.wait_for(lambda: self.server.packets(openrgb.REQUEST_LOAD_PROFILE)))
        self.assertEqual(self.server.packets(openrgb.REQUEST_LOAD_PROFILE)[0][1], b"Normal\0")

    def test_disabled_sync_never_connects(self):
        sync = openrgb.RGBSync()
        sync.configure(dict(openrgb_enabled=False, openrgb_host="127.0.0.1", openrgb_port=self.server.port,
                            openrgb_devices=[], openrgb_brightness=1.0, openrgb_restore_profile=""))
        sync.start()
        sync.set_colour((1.0, 1.0, 1.0))
        time.sleep(0.3)
        sync.stop()
        self.assertEqual(self.server.received, [])

    def test_unreachable_server_reports_status_and_keeps_running(self):
        statuses = []
        sync = openrgb.RGBSync(on_status=statuses.append)
        sync.configure(dict(openrgb_enabled=True, openrgb_host="127.0.0.1", openrgb_port=1,
                            openrgb_devices=[], openrgb_brightness=1.0, openrgb_restore_profile=""))
        sync.start()
        sync.set_colour((1.0, 0.0, 0.0))
        self.assertTrue(self.server.wait_for(lambda: statuses))
        self.assertIn("not reachable", statuses[0])
        self.assertTrue(sync.is_alive())
        sync.stop()
        self.assertFalse(sync.is_alive())


if __name__ == "__main__":
    unittest.main()
