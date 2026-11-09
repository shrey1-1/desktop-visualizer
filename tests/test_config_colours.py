import colorsys
import json
import random
import tempfile
import unittest
from pathlib import Path

from desktop_visualizer import config
from desktop_visualizer.colours import (PALETTES, ColourEngine, gradient_style_id, hex_to_rgb, palette_colours,
                                        rgb_to_hex)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "sub" / "config.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_defaults_when_missing_or_broken(self):
        self.assertEqual(config.load(self.path), config.DEFAULTS)
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(config.load(self.path), config.DEFAULTS)

    def test_bad_values_fall_back_to_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"x": -5, "size": True, "colour_mode": "plaid", "fixed_colour": "red",
                                         "opacity": 7, "unknown": 1}))
        loaded = config.load(self.path)
        self.assertEqual(loaded["x"], 0)  # clamped into range
        self.assertEqual(loaded["size"], config.DEFAULTS["size"])
        self.assertEqual(loaded["colour_mode"], "album")
        self.assertEqual(loaded["fixed_colour"], config.DEFAULTS["fixed_colour"])
        self.assertEqual(loaded["opacity"], 1.0)
        self.assertNotIn("unknown", loaded)

    def test_update_merges_without_losing_other_keys(self):
        # The overlay saves its position while the settings window changes colours.
        config.update({"colour_mode": "rainbow"}, self.path)
        config.update({"x": 10, "y": 20, "size": 300}, self.path)
        loaded = config.load(self.path)
        self.assertEqual((loaded["colour_mode"], loaded["x"], loaded["size"]), ("rainbow", 10, 300))

    def test_update_rejects_invalid(self):
        with self.assertRaises(ValueError):
            config.update({"fixed_colour": "not a colour"}, self.path)
        with self.assertRaises(KeyError):
            config.update({"nope": 1}, self.path)

    def test_colour_normalised_and_int_rounded(self):
        loaded = config.update({"fixed_colour": "#AABBCC", "openrgb_port": 6742.0}, self.path)
        self.assertEqual(loaded["fixed_colour"], "#aabbcc")
        self.assertIsInstance(loaded["openrgb_port"], int)

    def test_layer_options(self):
        for layer in ("top", "overlay", "bottom"):
            self.assertEqual(config.update({"layer": layer}, self.path)["layer"], layer)
        with self.assertRaises(ValueError):
            config.update({"layer": "sideways"}, self.path)

    def test_reset(self):
        config.update({"colour_mode": "fixed", "x": 5}, self.path)
        loaded = config.reset(["colour_mode", "x"], self.path)
        self.assertEqual((loaded["colour_mode"], loaded["x"]), ("album", None))


def settings(**overrides):
    s = dict(config.DEFAULTS)
    s["transition"] = 0.0
    s.update(overrides)
    return s


def hue(rgb):
    return colorsys.rgb_to_hsv(*rgb)[0]


def close(a, b):
    return all(abs(x - y) < 1e-6 for x, y in zip(a, b))


class ColourEngineTest(unittest.TestCase):
    def test_hex_round_trip(self):
        self.assertEqual(rgb_to_hex(hex_to_rgb("#1ed760")), "#1ed760")

    def test_album_mode_follows_cover(self):
        engine = ColourEngine(settings())
        engine.on_track(None, now=0)
        engine.on_track((1.0, 0.0, 0.0), now=0)
        primary, secondary = engine.tick(1)
        self.assertEqual(primary, (1.0, 0.0, 0.0))
        self.assertEqual(primary, secondary)

    def test_fixed_mode_ignores_cover(self):
        engine = ColourEngine(settings(colour_mode="fixed", fixed_colour="#00ff00"))
        engine.on_track((1.0, 0.0, 0.0), now=0)
        self.assertEqual(engine.tick(1)[0], (0.0, 1.0, 0.0))

    def test_switching_mode_applies_immediately(self):
        engine = ColourEngine(settings())
        engine.apply_settings(settings(colour_mode="fixed", fixed_colour="#0000ff"), now=0)
        self.assertEqual(engine.tick(0.1)[0], (0.0, 0.0, 1.0))

    def test_transition_fades(self):
        engine = ColourEngine(settings(colour_mode="fixed", fixed_colour="#000000", transition=2.0))
        engine.tick(10)
        engine.apply_settings(settings(colour_mode="fixed", fixed_colour="#ffffff", transition=2.0), now=10)
        middle = engine.tick(11)[0]
        self.assertTrue(0.2 < middle[0] < 0.8)
        self.assertEqual(engine.tick(12.5)[0], (1.0, 1.0, 1.0))

    def test_random_per_song_changes_each_song(self):
        engine = ColourEngine(settings(colour_mode="random"), rng=random.Random(1))
        colours = []
        for n in range(5):
            engine.on_track(None, now=n)
            colours.append(engine.tick(n)[0])
        self.assertEqual(len(set(colours)), 5)
        for a, b in zip(colours, colours[1:]):  # never two near-identical hues in a row
            distance = abs(hue(a) - hue(b))
            self.assertGreater(min(distance, 1 - distance), 0.15)

    def test_random_interval(self):
        engine = ColourEngine(settings(colour_mode="random", random_when="interval", random_interval=5),
                              rng=random.Random(2))
        first = engine.tick(1)[0]
        self.assertEqual(engine.tick(4)[0], first)
        self.assertNotEqual(engine.tick(6)[0], first)

    def test_random_from_palette(self):
        engine = ColourEngine(settings(colour_mode="random", random_from="palette", palette="ocean"),
                              rng=random.Random(3))
        allowed = palette_colours("ocean")
        for n in range(10):
            engine.on_track(None, now=n)
            colour = engine.tick(n)[0]
            self.assertTrue(any(close(colour, c) for c in allowed), colour)

    def test_palette_cycle(self):
        engine = ColourEngine(settings(colour_mode="palette", palette="fire", palette_interval=4))
        fire = palette_colours("fire")
        self.assertTrue(close(engine.tick(1)[0], fire[0]))
        self.assertTrue(close(engine.tick(4.5)[0], fire[1]))
        self.assertTrue(close(engine.tick(9)[0], fire[2]))

    def test_rainbow_moves_through_hues(self):
        engine = ColourEngine(settings(colour_mode="rainbow", rainbow_period=10))
        self.assertAlmostEqual(hue(engine.tick(0)[0]), 0.0, places=3)
        self.assertAlmostEqual(hue(engine.tick(2.5)[0]), 0.25, places=3)
        self.assertAlmostEqual(hue(engine.tick(12.5)[0]), 0.25, places=3)

    def test_gradients(self):
        base = settings(colour_mode="fixed", fixed_colour="#ff0000")
        primary, secondary = ColourEngine(dict(base, gradient="complementary")).tick(1)
        self.assertAlmostEqual(hue(secondary), 0.5, places=3)
        primary, secondary = ColourEngine(dict(base, gradient="analogous")).tick(1)
        self.assertAlmostEqual(hue(secondary), 0.12, places=3)
        primary, secondary = ColourEngine(dict(base, gradient="custom", gradient_colour="#0000ff")).tick(1)
        self.assertEqual(secondary, (0.0, 0.0, 1.0))
        self.assertEqual(gradient_style_id(dict(base, gradient="off")), 0)
        self.assertEqual(gradient_style_id(dict(base, gradient="custom", gradient_style="radial")), 3)

    def test_brightness_and_saturation(self):
        engine = ColourEngine(settings(colour_mode="fixed", fixed_colour="#ff0000", saturation=0.0, brightness=0.5))
        r, g, b = engine.tick(1)[0]
        self.assertAlmostEqual(r, 0.5)
        self.assertAlmostEqual(g, 0.5)  # no saturation = grey

    def test_unknown_palette_falls_back(self):
        self.assertEqual(palette_colours("missing"), palette_colours("neon"))
        self.assertIn("neon", PALETTES)


if __name__ == "__main__":
    unittest.main()
