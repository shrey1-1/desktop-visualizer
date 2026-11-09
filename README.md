# Desktop Visualizer

The NCS visualizer from [Konsl/spicetify-visualizer](https://github.com/Konsl/spicetify-visualizer),
running on your Linux desktop and reacting live to your music.

- A glowing sphere of dots that moves with the music and floats over your windows. Clicks pass through it.
- Works with Spotify, or with any audio playing on your computer.
- Colours from the album cover, a fixed colour, random colours, a rainbow cycle or colour palettes, with optional gradients.
- Can make your keyboard, mouse and other RGB lighting match, through [OpenRGB](https://openrgb.org).
- Fades away when the music stops.

It runs on Linux only. It works best on **KDE Plasma**, **Hyprland** and **Sway**, and also runs on
GNOME and X11 desktops ([details](#supported-desktops)).

---

## Install

The whole install takes about two minutes. You need a terminal; copy each command and press Enter.

### Step 1: Install what it needs

Run the command for your Linux distribution. It asks for your password.

**Arch, CachyOS, Manjaro, EndeavourOS**
```sh
sudo pacman -S --needed git pyside6 qt6-webengine python-numpy libpulse playerctl layer-shell-qt
```

**Fedora**
```sh
sudo dnf install git python3-pyside6 qt6-qtwebengine python3-numpy pulseaudio-utils playerctl layer-shell-qt
```

**Debian, Ubuntu, Linux Mint, Pop!_OS**
```sh
sudo apt install git python3-numpy pulseaudio-utils playerctl layer-shell-qt \
  python3-pyside6.qtwidgets python3-pyside6.qtquick python3-pyside6.qtquickcontrols2 \
  python3-pyside6.qtwebenginequick python3-pyside6.qtnetwork \
  qml6-module-qtquick-controls qml6-module-qtquick-dialogs qml6-module-qtquick-layouts qml6-module-qtwebengine
```

**openSUSE**
```sh
sudo zypper install git python3-pyside6 python3-numpy pulseaudio-utils playerctl layer-shell-qt6
```

> Only the Arch command has been tested. Package names on other distributions can differ. If one
> fails, the installer in step 2 tells you exactly what's still missing, and please
> [open an issue](https://github.com/shrey1-1/desktop-visualizer/issues) so it can be fixed.
>
> Use your distribution's packages, not `pip install PySide6`. The pip version can't keep the
> visualizer on top of other windows.

### Step 2: Download and install it

```sh
git clone https://github.com/shrey1-1/desktop-visualizer.git
cd desktop-visualizer
./install.sh
```

You should see a list of `ok` lines, then **Installed.**

- If a line says `MISSING`, install that package (the installer prints the command for your
  distro) and run `./install.sh` again.
- No root is needed. Everything goes into your home folder (`~/.local`).

### Step 3: Start it

Open your app menu and search for **Desktop Visualizer**. Or run `desktop-visualizer` in a terminal.

Then **play a song in Spotify**. The visualizer stays invisible while nothing is playing, so
don't worry if you see nothing at first.

### Arch Linux: install as a package instead (optional)

Instead of step 2, you can build a normal pacman package:

```sh
git clone https://github.com/shrey1-1/desktop-visualizer.git
cd desktop-visualizer/packaging/arch
makepkg -si
```

### Updating

```sh
cd desktop-visualizer        # the folder you cloned in step 2
git pull
./install.sh
```

Your settings are kept. If the visualizer is running, it restarts with the new version.

### Uninstalling

```sh
cd desktop-visualizer
./install.sh --uninstall     # removes the app, keeps your settings
./install.sh --purge         # removes the app and your settings
```

---

## How to use it

### First run: what to expect

1. Start **Desktop Visualizer** from the app menu.
2. Play music in **Spotify**. A sphere of dots appears in the middle of the screen and moves with the music.
3. A **tray icon** appears next to the clock. On KDE it may be hidden under the small **^** arrow.
4. Pause the music, and after about 2 seconds the sphere fades away. It comes back when you press play.

The sphere lets clicks pass through, so you can keep using the windows underneath it.

> **Want it to react to YouTube, a browser, games or any other app?**
> Open the settings (below) and go to **Audio**, then **All system audio**.

### Show and hide it

| To… | Do this |
| --- | --- |
| Show it | Open **Desktop Visualizer** from the app menu |
| Hide it | Open **Desktop Visualizer** from the app menu again, or right-click the tray icon → **Quit** |
| Start it automatically when you log in | Settings → **General** → *Start the visualizer when I log in* |

### Move and resize it

1. **Click the tray icon.** A white frame appears around the visualizer.
2. **Drag inside the frame** to move it.
3. **Drag the corner handle** (bottom right), or **scroll** over it, to resize it.
4. When you're happy, **double-click it** or press **Esc**.

Its position and size are saved for next time. To put it back in the middle, right-click the tray
icon → **Centre on screen**.

### Open the settings

Use any of these:
- right-click the tray icon → **Settings…**
- right-click **Desktop Visualizer** in the app menu → **Settings**
- run `desktop-visualizer --settings`

Changes apply instantly. You don't need to restart anything.

### What you can change

| Tab | Options |
| --- | --- |
| **Colours** | Where the colour comes from: the **album cover** (default), **one fixed colour**, **random** (every song or every few seconds), a **rainbow** cycle, or a **palette** cycle (Neon, Synthwave, Sunset, Ocean, Forest, Fire, Ice, Candy). Add a **second colour** for a gradient. Adjust brightness, saturation and fade speed. |
| **Keyboard RGB** | Make your keyboard and other RGB devices match the visualizer ([setup below](#keyboard-and-rgb-lighting)). |
| **Display** | Size, see-through amount, and **where it shows**: on top of windows, on top of everything (even fullscreen games and videos), or **desktop only** (behind all windows, like a live wallpaper). Choose whether it fades out when the music stops. |
| **Audio** | **Spotify only** or **all system audio**. Sensitivity is automatic, or you can set it yourself. |
| **General** | Start at login. Reset everything. |

### Keyboard and RGB lighting

This makes your keyboard (and mouse, fans, RAM… anything OpenRGB supports) change colour with the
visualizer. It's optional.

1. Install **OpenRGB** (Arch: `sudo pacman -S openrgb`; other distros: [openrgb.org](https://openrgb.org)).
2. Open OpenRGB and check that it shows your keyboard.
3. In OpenRGB, open the **Settings** tab, then **SDK Server**, and click **Start Server**.
   To have it work after a restart, also tick OpenRGB's options to start at login, start minimized and start the server.
4. **Optional:** set up the lighting you normally use, then save it as a profile (Profiles → Save).
5. In the visualizer's settings, open **Keyboard RGB**, turn on **Sync colours to OpenRGB devices**,
   click **Find devices**, and choose which devices should follow along.
6. **Optional:** under *When the visualizer closes*, pick the profile from step 4. Your normal lighting
   then comes back whenever you close the visualizer.

To stop syncing, turn the switch off again. If you picked a profile in step 6, your lighting returns to it.

### Command line

```
desktop-visualizer               show it, or hide it if it's already showing
desktop-visualizer --start       show it (does nothing if it's already showing)
desktop-visualizer --quit        hide it
desktop-visualizer --edit        show it and start move/resize mode
desktop-visualizer --settings    open the settings window
desktop-visualizer --foreground  run it in the terminal and print messages (for troubleshooting)
```

---

## Troubleshooting

**Nothing appears.**
- Is music actually playing? It stays hidden during silence. You can turn that off: Settings →
  Display → *Fade out when the music stops*.
- Using something other than Spotify? Settings → Audio → **All system audio**.
- Run `desktop-visualizer --quit`, then `desktop-visualizer --foreground`, and read the messages
  it prints. Messages from normal runs are saved in `~/.cache/desktop-visualizer/log.txt`.

**There's no tray icon (GNOME).**
GNOME hides tray icons unless you install the *AppIndicator and KStatusNotifierItem Support*
extension. Without it, use the app menu: right-click Desktop Visualizer → **Settings** or
**Move / resize**.

**It goes behind other windows, or doesn't cover fullscreen apps.**
Settings → Display → *Show it* → **On top of everything**. On KDE, Hyprland and Sway make sure
`layer-shell-qt` is installed (step 1). On GNOME it stays on top as an ordinary always-on-top window.

**The `desktop-visualizer` command isn't found.**
`~/.local/bin` isn't on your PATH. The app menu still works, or run `~/.local/bin/desktop-visualizer`.

**The keyboard doesn't change colour.**
Check that OpenRGB is running with its SDK server started (see step 3 above), then click **Find
devices** in Settings → Keyboard RGB. Messages are in `~/.cache/desktop-visualizer/log.txt`.

**Something else.** [Open an issue](https://github.com/shrey1-1/desktop-visualizer/issues) and include the output of
`desktop-visualizer --foreground`.

---

## Supported desktops

| Desktop | How it stays on top |
| --- | --- |
| KDE Plasma, Hyprland, Sway and other wlroots compositors (Wayland) | layer-shell, the best option (needs `layer-shell-qt`) |
| GNOME (Wayland) | always-on-top window through XWayland |
| Any X11 desktop | always-on-top window |

Audio capture needs PipeWire (the default on most distros today) or PulseAudio. To force a mode,
set `DESKTOP_VISUALIZER_BACKEND=layer-shell` or `x11`.

## How it works

- `audio.py` finds Spotify's audio stream with `pactl` (or listens to everything for "all system
  audio") and records it with `parec`. It turns each 20 ms of sound into a loudness level.
- `track.py` reads the current song with `playerctl`. Each song gets its own dot pattern, and the
  album cover provides the colour.
- `colours.py` decides the colours from your settings. `openrgb.py` is a small OpenRGB client
  that needs no extra packages.
- `web/` draws the visualizer. The drawing code comes from the original Spicetify project, with an
  added gradient option. The input is live audio instead of Spotify's pre-analysed song data, so the
  motion trails the music by about 50–100 ms.
- `qml/` contains the overlay window and the settings window. Settings are stored in
  `~/.config/desktop-visualizer/config.json`.

## Development

```sh
python3 -m unittest discover -s tests       # run the tests
python3 -m desktop_visualizer --foreground  # run straight from the source folder
```

## License

MIT. The drawing code and shaders come from Konsl/spicetify-visualizer, also MIT. See
`LICENSE` and `LICENSE-spicetify-visualizer`.
