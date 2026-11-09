import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: win

    readonly property var s: backend.settings
    property var rgbDevices: []
    property var rgbProfiles: []
    property string rgbStatus: ""
    property bool rgbScanning: false

    width: 640
    height: 720
    minimumWidth: 480
    minimumHeight: 420
    visible: true
    title: "Desktop Visualizer Settings"

    // ---- reusable rows ----

    // Slider bound to a setting; follows outside changes except while being dragged.
    component SettingSlider: RowLayout {
        id: row

        property string key
        property real from: 0
        property real to: 1
        property real stepSize: 0.01
        property int decimals: 2
        property string suffix: ""
        property real scale: 1 // shown value = stored value * scale

        Layout.fillWidth: true

        Slider {
            id: slider

            Layout.fillWidth: true
            from: row.from
            to: row.to
            // No stepSize: some styles draw a tick mark per step. Round when saving instead.
            onMoved: backend.set(row.key, Math.round(value / row.stepSize) * row.stepSize)

            Binding on value {
                value: win.s[row.key]
                when: !slider.pressed
            }
        }

        Label {
            Layout.minimumWidth: 64
            horizontalAlignment: Text.AlignRight
            text: (slider.value * row.scale).toFixed(row.decimals) + row.suffix
        }
    }

    component SettingCombo: ComboBox {
        id: combo

        property string key
        // [[label, value], ...]
        property var options: []

        Layout.fillWidth: true
        model: options.map(o => o[0])
        onActivated: index => backend.set(key, options[index][1])

        Binding on currentIndex {
            value: Math.max(0, combo.options.findIndex(o => o[1] === win.s[combo.key]))
        }
    }

    component SettingSwitch: Switch {
        id: sw

        property string key

        onToggled: backend.set(key, checked)

        Binding on checked {
            value: !!win.s[sw.key]
        }
    }

    component Swatch: Rectangle {
        property color swatchColor
        property bool selected: false
        signal clicked

        implicitWidth: 34
        implicitHeight: 34
        radius: 8
        color: swatchColor
        border.width: selected ? 3 : 1
        border.color: selected ? win.palette.highlight : Qt.rgba(0.5, 0.5, 0.5, 0.6)

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }
    }

    component ColourButton: RowLayout {
        id: cb

        property string key
        property string title: "Choose colour"

        Swatch {
            swatchColor: win.s[cb.key]
            onClicked: dialog.open()
        }
        Button {
            text: "Custom…"
            onClicked: dialog.open()
        }
        ColorDialog {
            id: dialog

            title: cb.title
            selectedColor: win.s[cb.key]
            onAccepted: backend.set(cb.key, selectedColor.toString().slice(0, 7))
        }
    }

    component Section: Label {
        Layout.topMargin: 14
        font.bold: true
        font.pointSize: Qt.application.font.pointSize * 1.15
    }

    component Hint: Label {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        opacity: 0.75
    }

    component SettingsPage: ScrollView {
        id: page

        default property alias content: column.data

        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            id: column

            width: page.availableWidth - 32
            x: 16
            y: 8
            spacing: 8
        }
    }

    // ---- layout ----

    header: TabBar {
        id: tabs

        TabButton { text: "Colours" }
        TabButton { text: "Keyboard RGB" }
        TabButton { text: "Display" }
        TabButton { text: "Audio" }
        TabButton { text: "General" }
    }

    footer: Label {
        id: errorLabel

        padding: 8
        visible: text !== ""
        color: "#e5484d"
        wrapMode: Text.WordWrap
    }

    Connections {
        target: backend

        function onError(message) {
            errorLabel.text = message;
        }

        function onOpenrgbScanned(devices, profiles, error) {
            win.rgbScanning = false;
            win.rgbDevices = devices;
            win.rgbProfiles = profiles;
            win.rgbStatus = error !== "" ? error : devices.length + " device(s) found";
        }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: tabs.currentIndex

        // ---------------- Colours ----------------
        SettingsPage {
            Section { text: "Colour source" }
            SettingCombo {
                key: "colour_mode"
                options: [["Album cover (changes with each song)", "album"], ["One fixed colour", "fixed"],
                          ["Random", "random"], ["Rainbow cycle", "rainbow"], ["Cycle through a palette", "palette"]]
            }

            // Fixed
            ColumnLayout {
                visible: s.colour_mode === "fixed"
                Layout.fillWidth: true

                Hint { text: "Pick a preset or choose any colour." }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: backend.presets

                        Swatch {
                            required property var modelData
                            swatchColor: modelData.colour
                            selected: s.fixed_colour === modelData.colour
                            onClicked: backend.set("fixed_colour", modelData.colour)
                            ToolTip.visible: hover.hovered
                            ToolTip.text: modelData.name
                            HoverHandler { id: hover }
                        }
                    }
                }
                ColourButton { key: "fixed_colour" }
            }

            // Random
            GridLayout {
                visible: s.colour_mode === "random"
                Layout.fillWidth: true
                columns: 2

                Label { text: "Change" }
                SettingCombo {
                    key: "random_when"
                    options: [["On every new song", "song"], ["Every few seconds", "interval"]]
                }
                Label { text: "Every"; visible: s.random_when === "interval" }
                SettingSlider {
                    visible: s.random_when === "interval"
                    key: "random_interval"; from: 1; to: 120; stepSize: 1; decimals: 0; suffix: " s"
                }
                Label { text: "Pick from" }
                SettingCombo {
                    key: "random_from"
                    options: [["Any bright colour", "any"], ["The palette below", "palette"]]
                }
            }

            // Rainbow
            GridLayout {
                visible: s.colour_mode === "rainbow"
                Layout.fillWidth: true
                columns: 2

                Label { text: "One full cycle takes" }
                SettingSlider { key: "rainbow_period"; from: 2; to: 120; stepSize: 1; decimals: 0; suffix: " s" }
            }

            // Palettes (palette cycle, or random from palette)
            ColumnLayout {
                visible: s.colour_mode === "palette" || (s.colour_mode === "random" && s.random_from === "palette")
                Layout.fillWidth: true

                Section { text: "Palette" }
                Repeater {
                    model: backend.palettes

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true

                        RadioButton {
                            text: modelData.name
                            checked: s.palette === modelData.id
                            Layout.minimumWidth: 130
                            onClicked: backend.set("palette", modelData.id)
                        }
                        Repeater {
                            model: modelData.colours

                            Rectangle {
                                required property string modelData
                                width: 26
                                height: 26
                                radius: 6
                                color: modelData
                            }
                        }
                    }
                }
                RowLayout {
                    visible: s.colour_mode === "palette"
                    Layout.fillWidth: true

                    Label { text: "Next colour every" }
                    SettingSlider { key: "palette_interval"; from: 1; to: 120; stepSize: 1; decimals: 0; suffix: " s" }
                }
            }

            Section { text: "Gradient" }
            GridLayout {
                Layout.fillWidth: true
                columns: 2

                Label { text: "Second colour" }
                SettingCombo {
                    key: "gradient"
                    options: [["Off (one colour)", "off"], ["Complementary (opposite hue)", "complementary"],
                              ["Analogous (neighbouring hue)", "analogous"], ["Custom colour", "custom"]]
                }
                Label { text: "Custom colour"; visible: s.gradient === "custom" }
                ColourButton { key: "gradient_colour"; visible: s.gradient === "custom"; title: "Gradient colour" }
                Label { text: "Direction"; visible: s.gradient !== "off" }
                SettingCombo {
                    visible: s.gradient !== "off"
                    key: "gradient_style"
                    options: [["Top to bottom", "vertical"], ["Diagonal", "diagonal"], ["Centre outwards", "radial"]]
                }
            }

            Section { text: "Fine-tuning" }
            GridLayout {
                Layout.fillWidth: true
                columns: 2

                Label { text: "Brightness" }
                SettingSlider { key: "brightness"; from: 0.3; to: 1.5; scale: 100; decimals: 0; suffix: " %" }
                Label { text: "Saturation" }
                SettingSlider { key: "saturation"; from: 0; to: 1.5; scale: 100; decimals: 0; suffix: " %" }
                Label { text: "Fade between colours"; visible: s.colour_mode !== "rainbow" }
                SettingSlider {
                    visible: s.colour_mode !== "rainbow"
                    key: "transition"; from: 0; to: 5; stepSize: 0.1; decimals: 1; suffix: " s"
                }
            }

            Button {
                Layout.topMargin: 12
                text: "Reset colour settings"
                onClicked: backend.resetKeys(["colour_mode", "fixed_colour", "random_when", "random_interval",
                    "random_from", "palette", "palette_interval", "rainbow_period", "transition", "gradient",
                    "gradient_colour", "gradient_style", "brightness", "saturation"])
            }
        }

        // ---------------- Keyboard RGB ----------------
        SettingsPage {
            Section { text: "Sync RGB devices with OpenRGB" }
            Hint {
                textFormat: Text.StyledText
                text: "Makes your keyboard (and mouse, RAM, fans… anything <a href=\"https://openrgb.org\">OpenRGB</a> "
                      + "supports) follow the visualizer's colour.<br>In OpenRGB, open <b>Settings → SDK Server</b>, "
                      + "click <b>Start Server</b>, and tick <b>Start server at startup</b>."
                onLinkActivated: link => Qt.openUrlExternally(link)
            }
            SettingSwitch { key: "openrgb_enabled"; text: "Sync colours to OpenRGB devices" }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                enabled: s.openrgb_enabled

                Label { text: "Server" }
                RowLayout {
                    Layout.fillWidth: true

                    TextField {
                        Layout.fillWidth: true
                        text: s.openrgb_host
                        placeholderText: "127.0.0.1"
                        onEditingFinished: if (text.trim() !== s.openrgb_host) backend.set("openrgb_host", text.trim() || "127.0.0.1")
                    }
                    SpinBox {
                        from: 1
                        to: 65535
                        editable: true
                        value: s.openrgb_port
                        textFromValue: v => String(v)
                        valueFromText: t => parseInt(t)
                        onValueModified: backend.set("openrgb_port", value)
                    }
                }
                Label { text: "Brightness" }
                SettingSlider { key: "openrgb_brightness"; from: 0; to: 1; scale: 100; decimals: 0; suffix: " %" }
            }

            Section { text: "Devices"; visible: s.openrgb_enabled }
            RowLayout {
                visible: s.openrgb_enabled

                Button {
                    text: win.rgbScanning ? "Searching…" : "Find devices"
                    enabled: !win.rgbScanning
                    onClicked: {
                        win.rgbScanning = true;
                        win.rgbStatus = "";
                        backend.scanOpenRGB();
                    }
                }
                BusyIndicator { running: win.rgbScanning; visible: running; implicitHeight: 28; implicitWidth: 28 }
            }
            Hint { visible: s.openrgb_enabled && win.rgbStatus !== ""; text: win.rgbStatus }
            CheckBox {
                visible: s.openrgb_enabled && win.rgbDevices.length > 0
                text: "All devices"
                checked: s.openrgb_devices.length === 0
                onClicked: backend.set("openrgb_devices", [])
            }
            Repeater {
                model: s.openrgb_enabled ? win.rgbDevices : []

                CheckBox {
                    required property var modelData
                    Layout.leftMargin: 24
                    text: modelData.name + "  (" + modelData.leds + " LEDs)"
                    checked: s.openrgb_devices.length === 0 || s.openrgb_devices.indexOf(modelData.name) >= 0
                    onClicked: {
                        let names = s.openrgb_devices.length === 0 ? win.rgbDevices.map(d => d.name) : s.openrgb_devices.slice();
                        if (checked && names.indexOf(modelData.name) < 0)
                            names.push(modelData.name);
                        if (!checked)
                            names = names.filter(n => n !== modelData.name);
                        if (names.length === win.rgbDevices.length)
                            names = [];
                        backend.set("openrgb_devices", names);
                    }
                }
            }

            Section { text: "When the visualizer closes"; visible: s.openrgb_enabled }
            SettingCombo {
                visible: s.openrgb_enabled
                key: "openrgb_restore_profile"
                options: [["Leave the last colour", ""]].concat(
                    win.rgbProfiles.concat(s.openrgb_restore_profile !== "" && win.rgbProfiles.indexOf(s.openrgb_restore_profile) < 0
                                           ? [s.openrgb_restore_profile] : [])
                        .map(p => ["Load OpenRGB profile “" + p + "”", p]))
            }
            Hint {
                visible: s.openrgb_enabled
                text: "Save your normal lighting as a profile in OpenRGB, then pick it here to get it back when the visualizer closes. Click Find devices to list your profiles."
            }
        }

        // ---------------- Display ----------------
        SettingsPage {
            Section { text: "Visualizer" }
            RowLayout {
                Label {
                    Layout.fillWidth: true
                    text: backend.overlayRunning ? "Showing" : "Not running"
                }
                Button {
                    text: backend.overlayRunning ? "Close it" : "Show it"
                    onClicked: backend.overlay(backend.overlayRunning ? "quit" : "start")
                }
            }

            Section { text: "Position and size" }
            RowLayout {
                Button {
                    text: "Move / resize on screen"
                    onClicked: backend.overlay("edit")
                }
                Button {
                    text: "Centre it"
                    enabled: backend.overlayRunning
                    onClicked: backend.overlay("centre")
                }
            }
            Hint { text: "You can also click the tray icon to move it. Drag to move, drag the corner or scroll to resize, double-click when done." }
            GridLayout {
                Layout.fillWidth: true
                columns: 2

                Label { text: "Size" }
                SettingSlider { key: "size"; from: 120; to: 1600; stepSize: 10; decimals: 0; suffix: " px" }
                Label { text: "Opacity" }
                SettingSlider { key: "opacity"; from: 0.1; to: 1; scale: 100; decimals: 0; suffix: " %" }
                Label { text: "Show it" }
                SettingCombo {
                    key: "layer"
                    options: [["On top of windows (below fullscreen games/videos)", "top"],
                              ["On top of everything, even fullscreen", "overlay"],
                              ["Desktop only (behind all windows, like a wallpaper)", "bottom"]]
                }
            }

            Section { text: "When nothing is playing" }
            SettingSwitch { key: "fade_when_silent"; text: "Fade out when the music stops" }
            RowLayout {
                visible: s.fade_when_silent
                Layout.fillWidth: true

                Label { text: "After" }
                SettingSlider { key: "fade_delay"; from: 0.5; to: 30; stepSize: 0.5; decimals: 1; suffix: " s" }
            }
        }

        // ---------------- Audio ----------------
        SettingsPage {
            Section { text: "What it listens to" }
            SettingCombo {
                key: "audio_source"
                options: [["Spotify only", "spotify"], ["All system audio (any app)", "system"]]
            }
            Hint {
                text: s.audio_source === "spotify"
                      ? "Only Spotify's sound moves the visualizer. Other apps, calls and games are ignored."
                      : "Reacts to everything your computer plays. Album colours come from whichever media player is active."
            }

            Section { text: "Sensitivity" }
            SettingSwitch { key: "auto_gain"; text: "Automatic (looks the same at any volume)" }
            RowLayout {
                visible: !s.auto_gain
                Layout.fillWidth: true

                Label { text: "Boost" }
                SettingSlider { key: "gain"; from: 0.5; to: 10; stepSize: 0.1; decimals: 1; suffix: "×" }
            }
        }

        // ---------------- General ----------------
        SettingsPage {
            Section { text: "Startup" }
            Switch {
                text: "Start the visualizer when I log in"
                checked: backend.autostart
                onToggled: backend.setAutostart(checked)
            }

            Section { text: "About" }
            Hint {
                textFormat: Text.StyledText
                text: "Desktop Visualizer. The NCS visualizer from "
                      + "<a href=\"https://github.com/Konsl/spicetify-visualizer\">Konsl/spicetify-visualizer</a> (MIT), "
                      + "running on your desktop and driven by live audio.<br><br>"
                      + "Command line: <tt>desktop-visualizer --help</tt>"
                onLinkActivated: link => Qt.openUrlExternally(link)
            }
            Button {
                Layout.topMargin: 12
                text: "Reset all settings"
                onClicked: resetDialog.open()
            }
        }
    }

    Dialog {
        id: resetDialog

        anchors.centerIn: parent
        title: "Reset all settings?"
        standardButtons: Dialog.Reset | Dialog.Cancel
        modal: true

        Label { text: "Colours, display, audio and RGB settings go back to their defaults." }

        onReset: {
            backend.resetKeys(Object.keys(backend.defaults));
            close();
        }
    }
}
