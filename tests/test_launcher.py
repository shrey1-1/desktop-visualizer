import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from desktop_visualizer import launcher
from desktop_visualizer.__main__ import parse_args


class BackendChoiceTest(unittest.TestCase):
    def test_kde_wayland_uses_layer_shell(self):
        env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}
        self.assertEqual(launcher.choose_backend(env, has_layer_shell=True), "layer-shell")

    def test_hyprland_uses_layer_shell(self):
        env = {"WAYLAND_DISPLAY": "wayland-1", "XDG_CURRENT_DESKTOP": "Hyprland"}
        self.assertEqual(launcher.choose_backend(env, has_layer_shell=True), "layer-shell")

    def test_gnome_falls_back(self):
        env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}
        self.assertEqual(launcher.choose_backend(env, has_layer_shell=True), "x11")

    def test_without_plugin_or_on_x11(self):
        self.assertEqual(launcher.choose_backend({"XDG_SESSION_TYPE": "wayland"}, has_layer_shell=False), "x11")
        self.assertEqual(launcher.choose_backend({"XDG_SESSION_TYPE": "x11"}, has_layer_shell=True), "x11")

    def test_override(self):
        env = {"XDG_SESSION_TYPE": "wayland", "DESKTOP_VISUALIZER_BACKEND": "x11"}
        self.assertEqual(launcher.choose_backend(env, has_layer_shell=True), "x11")


class GpuTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def make(self, *paths):
        for rel in paths:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def env(self):
        return launcher.dedicated_gpu_env(proc=self.root / "proc", glvnd_dirs=[self.root / "glvnd"],
                                          dri=self.root / "dri")

    def test_nvidia_prime_offload(self):
        self.make("proc/driver/nvidia/version", "glvnd/10_nvidia.json", "glvnd/50_mesa.json",
                  "dri/renderD128", "dri/renderD129")
        env = self.env()
        self.assertEqual(env["__NV_PRIME_RENDER_OFFLOAD"], "1")
        self.assertTrue(env["__EGL_VENDOR_LIBRARY_FILENAMES"].endswith("10_nvidia.json"))

    def test_other_hybrid_uses_dri_prime(self):
        self.make("dri/renderD128", "dri/renderD129")
        self.assertEqual(self.env(), {"DRI_PRIME": "1"})

    def test_single_gpu(self):
        self.make("dri/renderD128")
        self.assertIsNone(self.env())

    def supply(self, name, kind, online=None):
        d = self.root / "ps" / name
        d.mkdir(parents=True)
        (d / "type").write_text(kind + "\n")
        if online is not None:
            (d / "online").write_text(online + "\n")

    def test_power(self):
        self.supply("BAT0", "Battery")
        self.supply("ADP0", "Mains", "0")
        self.assertFalse(launcher.on_ac_power(self.root / "ps"))
        (self.root / "ps" / "ADP0" / "online").write_text("1\n")
        self.assertTrue(launcher.on_ac_power(self.root / "ps"))

    def test_desktop_without_battery_counts_as_plugged_in(self):
        self.root.joinpath("ps").mkdir()
        self.assertTrue(launcher.on_ac_power(self.root / "ps"))
        self.assertTrue(launcher.on_ac_power(self.root / "missing"))

    def test_choose_gpu(self):
        c = launcher.choose_gpu
        self.assertEqual(c("auto", True, True), "dedicated")
        self.assertEqual(c("auto", True, False), "integrated")
        self.assertEqual(c("dedicated", True, False), "dedicated")
        self.assertEqual(c("integrated", True, True), "integrated")
        self.assertEqual(c("dedicated", False, True), "integrated")  # nothing to switch to


class AutostartTest(unittest.TestCase):
    def test_enable_and_disable(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": tmp, "DESKTOP_VISUALIZER_LAUNCHER": "/usr/bin/true",
        }):
            self.assertFalse(launcher.autostart_enabled())
            launcher.set_autostart(True)
            self.assertTrue(launcher.autostart_enabled())
            text = launcher.autostart_path().read_text()
            self.assertIn("Exec=/usr/bin/true --start", text)
            launcher.set_autostart(False)
            self.assertFalse(launcher.autostart_enabled())

    def test_command_without_installed_launcher(self):
        with mock.patch.dict(os.environ, {"DESKTOP_VISUALIZER_LAUNCHER": ""}):
            command = launcher.launcher_command()
        self.assertIn(" -E -c ", command)
        self.assertIn(str(launcher.PACKAGE.parent), command)

    def test_current_folder_cannot_shadow_the_app(self):
        # A desktop_visualizer/ package in the working directory must not be imported.
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "desktop_visualizer")
            os.mkdir(fake)
            with open(os.path.join(fake, "__init__.py"), "w") as f:
                f.write("raise SystemExit('shadowed')\n")
            with open(os.path.join(fake, "__main__.py"), "w") as f:
                f.write("raise SystemExit('shadowed')\n")
            result = subprocess.run(
                [sys.executable, "-E", "-c", launcher.boot_code(launcher.PACKAGE.parent), "--version"],
                cwd=tmp, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("desktop-visualizer", result.stdout)


class CliTest(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(parse_args([]).action, "toggle")
        self.assertEqual(parse_args(["--start"]).action, "start")
        self.assertEqual(parse_args(["--settings"]).action, "settings")
        with self.assertRaises(SystemExit):
            parse_args(["--start", "--quit"])


if __name__ == "__main__":
    unittest.main()
