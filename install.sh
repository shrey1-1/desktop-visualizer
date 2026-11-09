#!/usr/bin/env bash
# Desktop Visualizer installer (per user, no root needed).
#
#   ./install.sh              install or update for the current user
#   ./install.sh --uninstall  remove it (keeps your settings)
#   ./install.sh --purge      remove it and your settings
#   ./install.sh --check      only check dependencies
#
# Run from a checkout of the repository. Installs to ~/.local by default; set PREFIX to change.
set -euo pipefail

APP=desktop-visualizer
PREFIX="${PREFIX:-$HOME/.local}"
APPDIR="$PREFIX/share/$APP"
BINDIR="$PREFIX/bin"
LAUNCHER="$BINDIR/$APP"
DESKTOP_FILE="$PREFIX/share/applications/$APP.desktop"
ICON_FILE="$PREFIX/share/icons/hicolor/scalable/apps/$APP.svg"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
AUTOSTART_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP.desktop"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

distro_family() {
	local id="" like=""
	if [[ -r /etc/os-release ]]; then
		id="$(. /etc/os-release && echo "${ID:-}")"
		like="$(. /etc/os-release && echo "${ID_LIKE:-}")"
	fi
	case " $id $like " in
	*" arch "*) echo arch ;;
	*" fedora "* | *" rhel "*) echo fedora ;;
	*" debian "* | *" ubuntu "*) echo debian ;;
	*" suse "* | *" opensuse "*) echo suse ;;
	*) echo unknown ;;
	esac
}

install_hint() {
	case "$(distro_family)" in
	arch) echo "sudo pacman -S --needed pyside6 qt6-declarative python-numpy libpulse playerctl layer-shell-qt" ;;
	fedora) echo "sudo dnf install python3-pyside6 python3-numpy pulseaudio-utils playerctl layer-shell-qt" ;;
	debian) echo "sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 python3-pyside6.qtopengl python3-pyside6.qtnetwork qml6-module-qtquick qml6-module-qtquick-controls qml6-module-qtquick-dialogs qml6-module-qtquick-layouts python3-numpy pulseaudio-utils playerctl layer-shell-qt" ;;
	suse) echo "sudo zypper install python3-pyside6 python3-numpy pulseaudio-utils playerctl layer-shell-qt6" ;;
	*) echo "Install PySide6 6.4 or newer (with Qt Quick, Qt Quick Controls and Qt OpenGL), numpy, pactl/parec (PulseAudio utils), playerctl and layer-shell-qt using your package manager." ;;
	esac
}

# Prefer the system Python: pip's PySide6 bundles its own Qt, which can't load the
# desktop's layer-shell plugin.
find_python() {
	local candidate
	for candidate in /usr/bin/python3 python3; do
		if command -v "$candidate" >/dev/null 2>&1 &&
			"$candidate" -c 'import PySide6.QtOpenGL, PySide6.QtQuick, PySide6.QtQuickControls2, PySide6.QtWidgets, numpy' 2>/dev/null; then
			command -v "$candidate"
			return 0
		fi
	done
	return 1
}

check_deps() {
	local missing=0 python
	bold "Checking dependencies"
	if python="$(find_python)"; then
		echo "  ok       Python with PySide6 (Qt Quick, OpenGL) and numpy ($python)"
	else
		echo "  MISSING  Python 3 with PySide6 6.4+ (Qt Quick, Qt Quick Controls, Qt OpenGL) and numpy"
		missing=1
	fi
	for cmd in pactl parec; do
		if command -v "$cmd" >/dev/null 2>&1; then
			echo "  ok       $cmd"
		else
			echo "  MISSING  $cmd (PulseAudio/PipeWire utilities)"
			missing=1
		fi
	done
	if command -v playerctl >/dev/null 2>&1; then
		echo "  ok       playerctl"
	else
		echo "  optional playerctl (needed for album-cover colours)"
	fi
	if [[ -n "${python:-}" ]] && PYTHONPATH="$SRC" "$python" -c 'from desktop_visualizer.launcher import layer_shell_available as a; raise SystemExit(0 if a() else 1)' 2>/dev/null; then
		echo "  ok       layer-shell-qt"
	else
		echo "  optional layer-shell-qt (keeps the overlay on top on KDE Plasma, Hyprland and Sway Wayland)"
	fi
	if [[ $missing -ne 0 ]]; then
		echo
		warn "Some required packages are missing. On this system, try:"
		echo "  $(install_hint)"
		return 1
	fi
	return 0
}

stop_running() {
	if [[ -x "$LAUNCHER" ]]; then
		"$LAUNCHER" --quit >/dev/null 2>&1 || true
	fi
}

do_uninstall() {
	stop_running
	rm -rf "$APPDIR"
	rm -f "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"
	# Only remove the login entry if it starts this copy (not one installed elsewhere).
	if [[ -f "$AUTOSTART_FILE" ]] && grep -qF "Exec=$LAUNCHER " "$AUTOSTART_FILE"; then
		rm -f "$AUTOSTART_FILE"
	fi
	if [[ "${1:-}" == purge ]]; then
		rm -rf "$CONFIG_DIR"
		echo "Removed Desktop Visualizer and its settings."
	else
		echo "Removed Desktop Visualizer. Your settings are still in $CONFIG_DIR (use --purge to remove them)."
	fi
	command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$PREFIX/share/applications" || true
}

do_install() {
	[[ -d "$SRC/desktop_visualizer" ]] || die "Run this from the desktop-visualizer folder (desktop_visualizer/ not found next to install.sh)."
	check_deps || exit 1
	local python
	python="$(find_python)"

	bold "Installing to $PREFIX"
	local was_running=0
	if [[ -x "$LAUNCHER" ]] && "$python" -c 'import sys; sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication
from desktop_visualizer import instance
QCoreApplication([])
raise SystemExit(0 if instance.send("overlay", "ping") else 1)' "$SRC" 2>/dev/null; then
		was_running=1
	fi
	stop_running

	mkdir -p "$APPDIR" "$BINDIR" "$(dirname "$DESKTOP_FILE")" "$(dirname "$ICON_FILE")"
	rm -rf "$APPDIR/desktop_visualizer"
	cp -r "$SRC/desktop_visualizer" "$APPDIR/"
	find "$APPDIR" -name __pycache__ -type d -prune -exec rm -rf {} +
	cp "$SRC"/LICENSE* "$APPDIR/" 2>/dev/null || true

	cat >"$LAUNCHER" <<EOF
#!/bin/sh
# Desktop Visualizer launcher (generated by install.sh)
export DESKTOP_VISUALIZER_LAUNCHER="$LAUNCHER"
exec "$python" -E -c 'import os, sys; sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != os.getcwd()]; sys.path.insert(0, sys.argv.pop(1)); from desktop_visualizer.__main__ import main; sys.exit(main())' "$APPDIR" "\$@"
EOF
	chmod +x "$LAUNCHER"

	sed "s|@LAUNCHER@|$LAUNCHER|g" "$SRC/data/$APP.desktop" >"$DESKTOP_FILE"
	cp "$SRC/desktop_visualizer/data/$APP.svg" "$ICON_FILE"
	command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$PREFIX/share/applications" || true
	command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true

	# Keep a start-at-login entry working: re-point it here only if it already starts this
	# copy or the program it starts is gone (never take over another installed copy's entry).
	if [[ -f "$AUTOSTART_FILE" ]]; then
		local current
		current="$(sed -n 's/^Exec=\([^ ]*\).*/\1/p' "$AUTOSTART_FILE" | head -n 1)"
		if [[ "$current" == "$LAUNCHER" || ! -x "$current" ]]; then
			sed -i "s|^Exec=.*|Exec=$LAUNCHER --start|" "$AUTOSTART_FILE"
		fi
	fi

	echo
	bold "Installed."
	echo "  Open \"Desktop Visualizer\" from your app menu, or run: $APP"
	echo "  Settings: tray icon → Settings…, or: $APP --settings"
	case ":$PATH:" in
	*":$BINDIR:"*) ;;
	*) warn "  Note: $BINDIR is not on your PATH, so the '$APP' command needs the full path (the app menu works anyway)." ;;
	esac

	if [[ $was_running -eq 1 ]]; then
		"$LAUNCHER" --start
		echo "  Restarted the running visualizer with the new version."
	fi
}

case "${1:-}" in
"") do_install ;;
--uninstall) do_uninstall ;;
--purge) do_uninstall purge ;;
--check) check_deps ;;
-h | --help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' ;;
*) die "Unknown option: $1 (see --help)" ;;
esac
