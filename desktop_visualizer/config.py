"""Settings: defaults, validation, and a JSON file shared by the overlay and the settings window.

Both processes write to the same file, so every write is a read-merge-write of only the
keys that changed. That way the overlay saving its position never undoes a colour change
made in the settings window, and the other way round.
"""

import json
import os
import re
from pathlib import Path

HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")

# name -> (default, validator). A validator returns the cleaned value or raises ValueError.


def _choice(*options):
    def check(value):
        if value not in options:
            raise ValueError(f"expected one of {options}")
        return value
    return check


def _number(lo, hi, integer=False):
    def check(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected a number")
        value = min(max(value, lo), hi)
        return int(round(value)) if integer else float(value)
    return check


def _boolean(value):
    if not isinstance(value, bool):
        raise ValueError("expected true/false")
    return value


def _colour(value):
    if not isinstance(value, str) or not HEX_COLOUR.match(value):
        raise ValueError("expected #rrggbb")
    return value.lower()


def _text(max_len=200):
    def check(value):
        if not isinstance(value, str):
            raise ValueError("expected text")
        return value[:max_len]
    return check


def _name_list(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("expected a list of names")
    return [v[:200] for v in value][:64]


def _optional_int(lo, hi):
    number = _number(lo, hi, integer=True)

    def check(value):
        return None if value is None else number(value)
    return check


SCHEMA = {
    # Placement (written by the overlay's move/resize mode)
    "x": (None, _optional_int(0, 100000)),
    "y": (None, _optional_int(0, 100000)),
    "size": (520, _number(120, 4000, integer=True)),
    # Display
    "opacity": (0.9, _number(0.1, 1.0)),
    "layer": ("top", _choice("top", "overlay", "bottom")),  # bottom = desktop only, behind windows
    "fade_when_silent": (True, _boolean),
    "fade_delay": (2.0, _number(0.5, 30.0)),
    # Look: "sphere" is the original; the others use live frequency data
    "style": ("sphere", _choice("sphere", "sphere_ring", "ring", "bars", "wave", "pulse")),
    # Performance
    "gpu": ("auto", _choice("auto", "dedicated", "integrated")),  # auto = dedicated when plugged in
    "frame_rate": (0, _number(0, 360, integer=True)),  # 0 = match the display's refresh rate
    # Audio
    "audio_source": ("spotify", _choice("spotify", "system")),
    "auto_gain": (True, _boolean),
    "gain": (2.5, _number(0.1, 20.0)),
    # Colours
    "colour_mode": ("album", _choice("album", "fixed", "random", "rainbow", "palette")),
    "fixed_colour": ("#4da3ff", _colour),
    "random_when": ("song", _choice("song", "interval")),
    "random_interval": (10.0, _number(1.0, 600.0)),
    "random_from": ("any", _choice("any", "palette")),
    "palette": ("neon", _text(40)),
    "palette_interval": (8.0, _number(1.0, 600.0)),
    "rainbow_period": (30.0, _number(2.0, 600.0)),
    "transition": (1.0, _number(0.0, 10.0)),
    "gradient": ("off", _choice("off", "complementary", "analogous", "custom")),
    "gradient_colour": ("#ff4da6", _colour),
    "gradient_style": ("vertical", _choice("vertical", "diagonal", "radial")),
    "brightness": (1.0, _number(0.3, 1.5)),
    "saturation": (1.0, _number(0.0, 1.5)),
    # Keyboard / peripheral RGB through OpenRGB
    "openrgb_enabled": (False, _boolean),
    "openrgb_host": ("127.0.0.1", _text(255)),
    "openrgb_port": (6742, _number(1, 65535, integer=True)),
    "openrgb_devices": ([], _name_list),  # empty = all devices
    "openrgb_brightness": (1.0, _number(0.0, 1.0)),
    "openrgb_restore_profile": ("", _text(200)),
}

DEFAULTS = {key: default for key, (default, _) in SCHEMA.items()}


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "desktop-visualizer" / "config.json"


def validate(key, value):
    """Return the cleaned value for a known key; raise KeyError/ValueError otherwise."""
    _, check = SCHEMA[key]
    return check(value)


def clean(data):
    """Keep only known keys with valid values; fill the rest with defaults."""
    result = dict(DEFAULTS)
    if isinstance(data, dict):
        for key, value in data.items():
            if key in SCHEMA:
                try:
                    result[key] = validate(key, value)
                except ValueError:
                    pass
    if result["openrgb_devices"] is DEFAULTS["openrgb_devices"]:
        result["openrgb_devices"] = []
    return result


def load(path=None):
    path = Path(path or config_path())
    try:
        return clean(json.loads(path.read_text()))
    except (OSError, ValueError):
        return clean({})


def update(changes, path=None):
    """Validate `changes`, merge them into the saved file and return the full settings."""
    path = Path(path or config_path())
    cleaned = {key: validate(key, value) for key, value in changes.items()}
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    raw.update(cleaned)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, indent=2, sort_keys=True))
    tmp.replace(path)
    return clean(raw)


def reset(keys, path=None):
    """Put the given keys back to their defaults."""
    return update({key: DEFAULTS[key] for key in keys}, path)
