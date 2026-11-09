import os
import tempfile
import unittest
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
        self.assertIn(" -I -c ", command)
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
                [sys.executable, "-I", "-c", launcher.boot_code(launcher.PACKAGE.parent), "--version"],
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
