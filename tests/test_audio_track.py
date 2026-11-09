import unittest

import numpy as np

from desktop_visualizer.audio import SAMPLE_RATE, LevelMeter, find_spotify_stream
from desktop_visualizer.track import pick_colour, track_seed


def stream(index, name=None, binary=None, corked=False):
    props = {}
    if name:
        props["application.name"] = name
    if binary:
        props["application.process.binary"] = binary
    return {"index": index, "corked": corked, "properties": props}


class FindSpotifyStreamTest(unittest.TestCase):
    def test_prefers_spotify_named_stream_over_chromium_helper(self):
        # Spicetify's web audio plays as a "Chromium" stream owned by spotify.
        streams = [
            stream(1, "WEBRTC VoiceEngine", "Discord"),
            stream(2, "Chromium", "spotify"),
            stream(3, "Spotify", None, corked=True),
        ]
        self.assertEqual(find_spotify_stream(streams), 3)

    def test_prefers_playing_stream(self):
        self.assertEqual(find_spotify_stream([stream(4, "Spotify", corked=True), stream(5, "Spotify")]), 5)

    def test_falls_back_to_spotify_binary(self):
        self.assertEqual(find_spotify_stream([stream(6, "Chromium", "spotify")]), 6)

    def test_ignores_other_apps(self):
        self.assertIsNone(find_spotify_stream([stream(7, "Firefox", "firefox"), stream(8)]))
        self.assertIsNone(find_spotify_stream([]))


def sine(amplitude, seconds):
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def feed_hops(meter, samples, hop=960):
    level = 0.0
    for i in range(0, len(samples), hop):
        level = meter.feed(samples[i:i + hop])
    return level


class LevelMeterTest(unittest.TestCase):
    def test_silence_is_zero(self):
        self.assertEqual(feed_hops(LevelMeter(), np.zeros(SAMPLE_RATE, dtype=np.float32)), 0.0)

    def test_auto_gain_ignores_volume(self):
        for amplitude in (0.1, 0.8):
            self.assertAlmostEqual(feed_hops(LevelMeter(), sine(amplitude, 1.0)), LevelMeter.TARGET_PEAK, places=2)

    def test_auto_gain_follows_dynamics(self):
        meter = LevelMeter()
        loud = feed_hops(meter, sine(0.6, 1.0))
        soft = feed_hops(meter, sine(0.2, 0.5))
        self.assertLess(soft, loud * 0.5)

    def test_very_quiet_audio_is_not_blown_up(self):
        self.assertLess(feed_hops(LevelMeter(), sine(0.01, 1.0)), 0.2)

    def test_fixed_gain_and_clamp(self):
        rms = 0.4 / np.sqrt(2)
        self.assertAlmostEqual(feed_hops(LevelMeter(gain=1.0), sine(0.4, 1.0)), rms, places=2)
        self.assertEqual(feed_hops(LevelMeter(gain=10.0), sine(0.4, 1.0)), 1.0)

    def test_gain_can_change_live(self):
        meter = LevelMeter()
        feed_hops(meter, sine(0.4, 0.5))
        meter.gain = 1.0
        self.assertAlmostEqual(feed_hops(meter, sine(0.4, 0.5)), 0.4 / np.sqrt(2), places=2)


class TrackTest(unittest.TestCase):
    def test_seed_is_stable_and_fits_int32(self):
        seed = track_seed("/com/spotify/track/abc")
        self.assertEqual(seed, track_seed("/com/spotify/track/abc"))
        self.assertNotEqual(seed, track_seed("/com/spotify/track/abd"))
        self.assertTrue(0 <= seed < 2**31)

    def test_pick_colour_follows_vivid_pixels(self):
        r, g, b = pick_colour([(20, 20, 20)] * 900 + [(200, 30, 40)] * 124)
        self.assertGreater(r, 0.85)
        self.assertLess(g, 0.4)
        self.assertLess(b, 0.4)

    def test_pick_colour_is_bright_for_grey_covers(self):
        self.assertGreaterEqual(max(pick_colour([(60, 60, 60)] * 100)), 0.89)

    def test_pick_colour_empty(self):
        self.assertIsNone(pick_colour([]))


if __name__ == "__main__":
    unittest.main()
