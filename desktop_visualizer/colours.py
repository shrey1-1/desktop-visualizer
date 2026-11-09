"""Decides the visualizer's colours from the settings, the current track and the time."""

import colorsys
import random

DEFAULT_COLOUR = (0x53 / 255, 0x53 / 255, 0x53 / 255)  # the original's fallback grey

# Swatches shown in the settings window for the fixed colour.
PRESETS = [
    ("Sky", "#4da3ff"), ("Cyan", "#22d3ee"), ("Mint", "#34d399"), ("Lime", "#a3e635"),
    ("Gold", "#facc15"), ("Orange", "#fb923c"), ("Red", "#f43f5e"), ("Pink", "#f472b6"),
    ("Violet", "#a78bfa"), ("Purple", "#c026d3"), ("White", "#f5f5f5"), ("Spotify", "#1ed760"),
]

PALETTES = {
    "neon": ("Neon", ["#ff2bd6", "#00f0ff", "#7cff00", "#ffe600", "#ff6b00"]),
    "synthwave": ("Synthwave", ["#ff2a6d", "#d300c5", "#7a04eb", "#05d9e8", "#ff9e00"]),
    "sunset": ("Sunset", ["#ff5e5b", "#ff9f45", "#ffd166", "#ef476f", "#c86bfa"]),
    "ocean": ("Ocean", ["#00b4d8", "#0077b6", "#48cae4", "#90e0ef", "#2ec4b6"]),
    "forest": ("Forest", ["#52b788", "#95d5b2", "#40916c", "#b7e4c7", "#d8f3dc"]),
    "fire": ("Fire", ["#ff4800", "#ff6d00", "#ff9100", "#ffb600", "#ff0a54"]),
    "ice": ("Ice", ["#caf0f8", "#ade8f4", "#90e0ef", "#a2d2ff", "#e0fbfc"]),
    "candy": ("Candy", ["#ffafcc", "#ffc8dd", "#cdb4db", "#bde0fe", "#a2d2ff"]),
}


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{round(min(max(c, 0), 1) * 255):02x}" for c in rgb)


def palette_colours(name):
    return [hex_to_rgb(c) for c in PALETTES.get(name, PALETTES["neon"])[1]]


def shift_hue(rgb, amount):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb((h + amount) % 1.0, s, v)


def adjust(rgb, saturation, brightness):
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    r, g, b = colorsys.hsv_to_rgb(h, min(s * saturation, 1.0), v)
    return (min(r * brightness, 1.0), min(g * brightness, 1.0), min(b * brightness, 1.0))


def smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class ColourEngine:
    """Call `tick(now)` regularly; it returns (primary, secondary) RGB tuples in 0..1.

    `secondary` equals `primary` when gradients are off.
    """

    def __init__(self, settings, rng=None):
        self.rng = rng or random.Random()
        self.settings = dict(settings)
        self.album = DEFAULT_COLOUR
        self.current = self._fixed_target()
        self.start_colour = self.current
        self.target = self.current
        self.transition_start = 0.0
        self.last_change = 0.0
        self.palette_index = 0
        self.now = 0.0
        self.retarget()

    # ---- inputs ----

    def apply_settings(self, settings, now=None):
        old = self.settings
        self.settings = dict(settings)
        keys = ("colour_mode", "fixed_colour", "random_from", "palette", "random_when")
        if any(old.get(k) != self.settings.get(k) for k in keys):
            self.retarget(now)

    def on_track(self, album_colour, now=None):
        """A new song started. `album_colour` is None until the cover has been analysed."""
        if album_colour is not None:
            self.album = album_colour
            if self.settings["colour_mode"] == "album":
                self._go_to(album_colour, now)
            return
        mode = self.settings["colour_mode"]
        if mode == "random" and self.settings["random_when"] == "song":
            self._go_to(self._random_colour(), now)

    # ---- targets ----

    def _fixed_target(self):
        return hex_to_rgb(self.settings["fixed_colour"])

    def _random_colour(self):
        if self.settings["random_from"] == "palette":
            choices = [c for c in palette_colours(self.settings["palette"]) if c != self.target] \
                or palette_colours(self.settings["palette"])
            return self.rng.choice(choices)
        # Any vivid colour, at least a sixth of the colour wheel away from the current one.
        current_hue = colorsys.rgb_to_hsv(*self.target)[0] if hasattr(self, "target") else 0.0
        hue = (current_hue + self.rng.uniform(1 / 6, 5 / 6)) % 1.0
        return colorsys.hsv_to_rgb(hue, self.rng.uniform(0.7, 1.0), 1.0)

    def retarget(self, now=None):
        mode = self.settings["colour_mode"]
        if mode == "album":
            self._go_to(self.album, now)
        elif mode == "fixed":
            self._go_to(self._fixed_target(), now)
        elif mode == "random":
            self._go_to(self._random_colour(), now)
        elif mode == "palette":
            colours = palette_colours(self.settings["palette"])
            self.palette_index %= len(colours)
            self._go_to(colours[self.palette_index], now)

    def _go_to(self, colour, now=None):
        now = self.now if now is None else now
        self.start_colour = self.current
        self.target = tuple(colour)
        self.transition_start = now
        self.last_change = now

    # ---- output ----

    def tick(self, now):
        self.now = now
        s = self.settings
        mode = s["colour_mode"]

        if mode == "rainbow":
            hue = (now / s["rainbow_period"]) % 1.0
            self.current = self.target = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        else:
            if mode == "random" and s["random_when"] == "interval" and now - self.last_change >= s["random_interval"]:
                self._go_to(self._random_colour(), now)
            elif mode == "palette" and now - self.last_change >= s["palette_interval"]:
                self.palette_index += 1
                colours = palette_colours(s["palette"])
                self._go_to(colours[self.palette_index % len(colours)], now)

            duration = s["transition"]
            t = 1.0 if duration <= 0 else smoothstep((now - self.transition_start) / duration)
            self.current = lerp(self.start_colour, self.target, t)

        primary = adjust(self.current, s["saturation"], s["brightness"])
        gradient = s["gradient"]
        if gradient == "complementary":
            secondary = shift_hue(primary, 0.5)
        elif gradient == "analogous":
            secondary = shift_hue(primary, 0.12)
        elif gradient == "custom":
            secondary = adjust(hex_to_rgb(s["gradient_colour"]), s["saturation"], s["brightness"])
        else:
            secondary = primary
        return primary, secondary


GRADIENT_STYLES = {"vertical": 1, "diagonal": 2, "radial": 3}


def gradient_style_id(settings):
    """Number passed to the shader: 0 = solid colour."""
    if settings["gradient"] == "off":
        return 0
    return GRADIENT_STYLES[settings["gradient_style"]]
