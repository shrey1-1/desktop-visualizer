"""Minimal client for the OpenRGB SDK server (Settings → SDK Server in OpenRGB, port 6742).

Only what the visualizer needs: list devices and profiles, switch devices to direct
control, set every LED to one colour, and load a profile. Protocol reference:
https://gitlab.com/CalcProgrammer1/OpenRGB/-/wikis/OpenRGB-SDK-Documentation
"""

import socket
import struct
import threading
import time

MAGIC = b"ORGB"
HEADER = struct.Struct("<4sIII")  # magic, device index, packet id, payload size

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
REQUEST_PROFILE_LIST = 150
REQUEST_LOAD_PROFILE = 152
RGBCONTROLLER_UPDATELEDS = 1050
RGBCONTROLLER_SETCUSTOMMODE = 1100

CLIENT_PROTOCOL = 4  # newest controller-data layout this parser understands


class OpenRGBError(Exception):
    pass


class Reader:
    """Sequential little-endian reader over a controller-data blob."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, n):
        if self.pos + n > len(self.data):
            raise OpenRGBError("truncated controller data")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def string(self):
        return self.take(self.u16()).rstrip(b"\0").decode("utf-8", "replace")

    def skip(self, n):
        self.take(n)


def parse_controller(data, protocol):
    """Return (name, led_count) from a REQUEST_CONTROLLER_DATA reply."""
    r = Reader(data)
    r.u32()  # data size
    r.i32()  # device type
    name = r.string()
    if protocol >= 1:
        r.string()  # vendor
    for _ in range(4):  # description, version, serial, location
        r.string()

    num_modes = r.u16()
    r.i32()  # active mode
    for _ in range(num_modes):
        r.string()  # mode name
        r.skip(4 + 4 + 4 + 4)  # value, flags, speed min, speed max
        if protocol >= 3:
            r.skip(8)  # brightness min, max
        r.skip(4 + 4 + 4)  # colours min, max, speed
        if protocol >= 3:
            r.skip(4)  # brightness
        r.skip(4 + 4)  # direction, colour mode
        r.skip(4 * r.u16())  # colours

    num_zones = r.u16()
    for _ in range(num_zones):
        r.string()  # zone name
        r.skip(4 + 4 + 4 + 4)  # type, leds min, max, count
        r.skip(r.u16())  # matrix (its length already includes height and width)
        if protocol >= 4:
            for _ in range(r.u16()):  # segments
                r.string()
                r.skip(4 + 4 + 4)

    led_count = r.u16()
    return name, led_count


def build_update_leds(rgb, led_count):
    r, g, b = (round(min(max(c, 0.0), 1.0) * 255) for c in rgb)
    colours = bytes((r, g, b, 0)) * led_count
    size = 4 + 2 + len(colours)
    return struct.pack("<IH", size, led_count) + colours


def parse_profiles(data):
    r = Reader(data)
    r.u32()  # data size
    return [r.string() for _ in range(r.u16())]


class Client:
    def __init__(self, host="127.0.0.1", port=6742, name="Desktop Visualizer", timeout=3.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.protocol = 0
        self._send(REQUEST_PROTOCOL_VERSION, struct.pack("<I", CLIENT_PROTOCOL))
        try:
            _, payload = self._recv(REQUEST_PROTOCOL_VERSION)
            self.protocol = min(struct.unpack("<I", payload[:4])[0], CLIENT_PROTOCOL)
        except socket.timeout:
            self.protocol = 0  # very old servers don't answer this
        self._send(SET_CLIENT_NAME, name.encode() + b"\0")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _send(self, packet_id, payload=b"", device=0):
        self.sock.sendall(HEADER.pack(MAGIC, device, packet_id, len(payload)) + payload)

    def _recv_exact(self, n):
        chunks = []
        while n:
            chunk = self.sock.recv(n)
            if not chunk:
                raise OpenRGBError("OpenRGB closed the connection")
            chunks.append(chunk)
            n -= len(chunk)
        return b"".join(chunks)

    def _recv(self, expected_id):
        # The server can push notifications (e.g. device list changed); skip those.
        while True:
            magic, device, packet_id, size = HEADER.unpack(self._recv_exact(HEADER.size))
            if magic != MAGIC:
                raise OpenRGBError("not an OpenRGB server")
            payload = self._recv_exact(size)
            if packet_id == expected_id:
                return device, payload

    def devices(self):
        """List of (index, name, led_count)."""
        self._send(REQUEST_CONTROLLER_COUNT)
        _, payload = self._recv(REQUEST_CONTROLLER_COUNT)
        count = struct.unpack("<I", payload[:4])[0]
        result = []
        for index in range(count):
            request = struct.pack("<I", self.protocol) if self.protocol >= 1 else b""
            self._send(REQUEST_CONTROLLER_DATA, request, device=index)
            _, data = self._recv(REQUEST_CONTROLLER_DATA)
            name, leds = parse_controller(data, self.protocol)
            result.append((index, name, leds))
        return result

    def profiles(self):
        if self.protocol < 2:
            return []
        self._send(REQUEST_PROFILE_LIST)
        _, payload = self._recv(REQUEST_PROFILE_LIST)
        return parse_profiles(payload)

    def load_profile(self, name):
        self._send(REQUEST_LOAD_PROFILE, name.encode() + b"\0")

    def set_direct(self, device):
        self._send(RGBCONTROLLER_SETCUSTOMMODE, device=device)

    def set_colour(self, device, led_count, rgb):
        if led_count:
            self._send(RGBCONTROLLER_UPDATELEDS, build_update_leds(rgb, led_count), device=device)


def scan(host, port):
    """Return (devices, profiles) or raise OSError/OpenRGBError. For the settings window."""
    with Client(host, port, name="Desktop Visualizer (settings)") as client:
        return [(name, leds) for _, name, leds in client.devices()], client.profiles()


class RGBSync(threading.Thread):
    """Keeps the selected OpenRGB devices set to the latest colour (newest wins, max ~30/s)."""

    MIN_INTERVAL = 1 / 30
    RETRY_SECONDS = 5.0

    def __init__(self, on_status=None):
        super().__init__(daemon=True, name="openrgb-sync")
        self.on_status = on_status or (lambda text: None)
        self.lock = threading.Condition()
        self.colour = None
        self.settings = None
        self.stopping = False
        self.dirty = False

    def configure(self, settings):
        keys = ("openrgb_enabled", "openrgb_host", "openrgb_port", "openrgb_devices",
                "openrgb_brightness", "openrgb_restore_profile")
        with self.lock:
            self.settings = {k: settings[k] for k in keys}
            self.dirty = True
            self.lock.notify()

    def set_colour(self, rgb):
        with self.lock:
            if rgb != self.colour:
                self.colour = rgb
                self.lock.notify()

    def stop(self, timeout=2.0):
        with self.lock:
            self.stopping = True
            self.lock.notify()
        self.join(timeout)

    def _wait_for_work(self, client, sent, active, next_retry):
        """Block (holding the lock) until there is something to do."""
        while not self.stopping and not self.dirty:
            enabled = bool(active and active["openrgb_enabled"])
            if enabled and client is None:
                remaining = next_retry - time.monotonic()
                if remaining <= 0:
                    return
                self.lock.wait(remaining)
            elif enabled and self.colour is not None and self.colour != sent:
                return
            else:
                self.lock.wait()

    def run(self):
        client, targets, sent, active, next_retry = None, [], None, None, 0.0
        while True:
            with self.lock:
                self._wait_for_work(client, sent, active, next_retry)
                if self.stopping:
                    break
                if self.dirty:
                    previous, active, self.dirty = active, self.settings, False
                    if client is not None and any(
                        previous[k] != active[k]
                        for k in ("openrgb_enabled", "openrgb_host", "openrgb_port", "openrgb_devices")
                    ):
                        self._restore(client, previous)
                        client.close()
                        client = None
                    sent, next_retry = None, 0.0  # brightness may have changed: resend
                colour = self.colour

            if not active["openrgb_enabled"]:
                continue

            if client is None:
                try:
                    client = Client(active["openrgb_host"], active["openrgb_port"])
                    wanted = set(active["openrgb_devices"])
                    targets = [(i, leds) for i, name, leds in client.devices() if not wanted or name in wanted]
                    for index, _ in targets:
                        client.set_direct(index)
                    self.on_status(f"Connected to OpenRGB ({len(targets)} device(s))")
                except (OSError, OpenRGBError) as err:
                    if client is not None:
                        client.close()
                    client = None
                    next_retry = time.monotonic() + self.RETRY_SECONDS
                    self.on_status(f"OpenRGB not reachable: {err}")
                    continue

            if colour is None:
                continue
            scaled = tuple(c * active["openrgb_brightness"] for c in colour)
            try:
                for index, leds in targets:
                    client.set_colour(index, leds, scaled)
                sent = colour
            except (OSError, OpenRGBError) as err:
                client.close()
                client = None
                next_retry = time.monotonic() + self.RETRY_SECONDS
                self.on_status(f"OpenRGB connection lost: {err}")
                continue
            time.sleep(self.MIN_INTERVAL)

        if client is not None:
            self._restore(client, active)
            client.close()

    @staticmethod
    def _restore(client, settings):
        profile = settings and settings.get("openrgb_restore_profile")
        if profile:
            try:
                client.load_profile(profile)
            except OSError:
                pass
