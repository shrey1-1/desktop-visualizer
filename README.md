# Desktop Visualizer

The NCS visualizer from [Konsl/spicetify-visualizer](https://github.com/Konsl/spicetify-visualizer),
running as a transparent overlay on your Linux desktop and reacting live to your music.

- Floats over your windows, and clicks pass through it
- Listens to Spotify only, or to all system audio
- Colours from the album cover, a fixed colour, random, rainbow or palette cycles, with optional two-colour gradients
- Can sync your keyboard, mouse and other RGB devices through [OpenRGB](https://openrgb.org)
- Settings window, tray icon, start at login
- Fades out when the music stops

## Install

### Any distro (per user, no root)

```sh
git clone https://github.com/shrey1-1/desktop-visualizer.git
cd desktop-visualizer
./install.sh
```

The installer checks dependencies first. If something is missing, it prints the install command
for your distro (Arch, Fedora, Debian/Ubuntu or openSUSE). It installs to `~/.local`
(`PREFIX=/some/path ./install.sh` to change), adds an app-menu entry, and restarts the visualizer
if it was running. Run it again to update.

### Arch Linux

```sh
cd packaging/arch
makepkg -si                                     # from the published release
LOCAL_SRC="$PWD/../.." makepkg -si              # or from this checkout
```

### Requirements

| | Arch package | Needed for |
| --- | --- | --- |
| Python 3.9+, PySide6 with Qt WebEngine and Qt Quick Controls | `pyside6 qt6-webengine` | everything |
| numpy | `python-numpy` | audio levels |
| `pactl` and `parec` (PipeWire or PulseAudio) | `libpulse` | audio capture |
| playerctl | `playerctl` | album-cover colours (optional) |
| layer-shell-qt | `layer-shell-qt` | keeping it on top on Wayland (optional, see below) |
| OpenRGB | `openrgb` | RGB device sync (optional) |

Use your distro's PySide6, not the one from pip. pip's copy bundles its own Qt, which can't load
the desktop's layer-shell plugin. Package names for other distros are in `install.sh`. They were
only tested on Arch (CachyOS), so please open an issue if one is wrong.

### Desktop support

| Session | How it stays on top |
| --- | --- |
| KDE Plasma, Hyprland, Sway and other wlroots compositors (Wayland) | layer-shell (best) |
| GNOME (Wayland) | always-on-top window through XWayland |
| Any X11 session | always-on-top window |

To force one or the other, set `DESKTOP_VISUALIZER_BACKEND=layer-shell` or `x11`.

## Use

- **App menu → Desktop Visualizer** shows it. Launching it again closes it.
- **Tray icon:** left-click toggles move/resize mode. Right-click for *Settings…*, *Centre on screen* and *Quit*.
- **Move / resize:** drag inside the frame to move, drag the corner or scroll to resize, then
  double-click or press Esc. The position is remembered.

```
desktop-visualizer             show it, or close it if it's showing
desktop-visualizer --start     show it (does nothing if already running)
desktop-visualizer --quit      close it
desktop-visualizer --edit      show it in move/resize mode
desktop-visualizer --settings  open the settings window
desktop-visualizer --foreground   run in the terminal with logs (debugging)
```

Logs from background runs are in `~/.cache/desktop-visualizer/log.txt`.

## Settings

Changes apply straight away. They're stored in `~/.config/desktop-visualizer/config.json`.

- **Colours:**
  - Colour source: album cover, a fixed colour (presets or any colour), random (every song or
    every N seconds, any bright colour or from a palette), rainbow cycle, or palette cycle. There
    are 8 palettes: Neon, Synthwave, Sunset, Ocean, Forest, Fire, Ice and Candy.
  - Optional second colour for a gradient: complementary, analogous or custom. It can run top to
    bottom, diagonally or from the centre outwards.
  - Brightness, saturation, and how long colours take to fade into each other.
- **Keyboard RGB:** sync to OpenRGB devices (all or selected), RGB brightness, and an OpenRGB
  profile to load when the visualizer closes.
- **Display:** size, opacity, whether it covers fullscreen apps, and fade-out when silent (with a delay).
- **Audio:** Spotify only or all system audio, and automatic or manual sensitivity.
- **General:** start at login, and reset all settings.

### Keyboard / RGB sync with OpenRGB

1. Install [OpenRGB](https://openrgb.org) and check that it detects your devices.
2. In OpenRGB, open **Settings → SDK Server**, click **Start Server**, and enable starting it with OpenRGB.
3. In Desktop Visualizer, go to **Settings → Keyboard RGB**, turn on sync, and click **Find devices**.
4. Optional: save your normal lighting as an OpenRGB profile and pick it under *When the visualizer closes*.

The visualizer switches the selected devices to direct mode and sets every LED to its main colour.

## How it works

- `audio.py` finds Spotify's stream with `pactl` (or uses the default output's monitor for
  "all system audio") and records it with `parec`. It turns each 20 ms of audio into a 0–1 level.
- `track.py` reads the current track over MPRIS with `playerctl`. Each song gets its own noise
  pattern, and the cover provides the album colour.
- `colours.py` decides the colours from the settings. `openrgb.py` is a small OpenRGB SDK client
  that uses only the standard library.
- `web/` holds the renderer. The shaders and render passes come from the original project. The
  final pass adds the optional gradient, and the input is live audio instead of Spotify's
  precomputed loudness data. Because of that, motion lags the music by roughly 50–100 ms.
- `qml/` contains the overlay, a full-screen transparent surface that only takes mouse input in
  move/resize mode, and the settings window. The settings window runs as a separate process and
  shares the config file with the overlay.

## Development

```sh
python3 -m unittest discover -s tests       # tests
python3 -m desktop_visualizer --foreground  # run from the checkout
```

## Uninstall

```sh
./install.sh --uninstall   # keeps your settings
./install.sh --purge       # also removes settings
```

## License

MIT. The rendering code and shaders come from Konsl/spicetify-visualizer, also MIT. See
`LICENSE` and `LICENSE-spicetify-visualizer`.
