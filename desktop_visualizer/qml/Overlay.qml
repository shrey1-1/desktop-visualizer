import QtQuick
import DesktopVisualizer

// Transparent surface covering the screen. Normally it ignores all input; in edit mode only
// the visualizer's box takes input (Python sets the input mask), so it can be moved and resized.
// OverlayLayerShell.qml wraps this to keep it above other windows on KDE/wlroots Wayland;
// elsewhere Python makes it an always-on-top window instead.
Window {
    id: root

    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus

    readonly property var settings: app.settings
    readonly property int minSize: 120
    property real boxX: 0
    property real boxY: 0
    property real boxSize: settings.size
    // Until moved, the starting spot is recomputed whenever the surface size changes,
    // because the compositor may report a temporary size first.
    property bool custom: false
    // Layer-shell only: shrink the surface to the visualizer box when not editing, so the
    // compositor doesn't blend a full-screen transparent surface every frame.
    property bool shrinkable: false
    readonly property bool boxSurface: shrinkable && !app.editing

    // ---- placement ----

    function clamp() {
        const sw = boxSurface ? screen.width : width;
        const sh = boxSurface ? screen.height : height;
        boxSize = Math.max(minSize, Math.min(boxSize, sw, sh));
        boxX = Math.max(0, Math.min(boxX, sw - boxSize));
        boxY = Math.max(0, Math.min(boxY, sh - boxSize));
    }

    function place() {
        if (boxSurface) {
            if (!custom) {
                boxSize = settings.size;
                const saved = settings.x != null && settings.y != null;
                boxX = saved ? settings.x : (screen.width - boxSize) / 2;
                boxY = saved ? settings.y : (screen.height - boxSize) / 2;
            }
            clamp();
            updateInputArea();
            return;
        }
        if (width <= 0 || height <= 0)
            return;
        if (!custom && !shrinkable) {
            boxSize = settings.size;
            const saved = settings.x != null && settings.y != null;
            boxX = saved ? settings.x : (width - boxSize) / 2;
            boxY = saved ? settings.y : (height - boxSize) / 2;
        }
        clamp();
        updateInputArea();
    }

    function updateInputArea() {
        if (boxSurface)
            app.setInputArea(0, 0, Math.round(boxSize));
        else
            app.setInputArea(Math.round(boxX), Math.round(boxY), Math.round(boxSize));
    }

    function save() {
        app.saveGeometry(Math.round(boxX), Math.round(boxY), Math.round(boxSize));
    }

    onWidthChanged: if (!boxSurface) place()
    onHeightChanged: if (!boxSurface) place()

    // ---- feeding the visualizer ----

    function sendAll() {
        view.setTrack(app.seed);
        view.setColors(app.colours);
        view.setFade(settings.fade_when_silent, settings.fade_delay);
        view.setEditing(app.editing);
        view.setFrameRate(app.frameRate);
    }

    Component.onCompleted: {
        place();
        sendAll();
    }

    Connections {
        target: app

        function onLevel(value) {
            view.pushLevel(value);
        }

        function onSeedChanged() {
            view.setTrack(app.seed);
        }

        function onColoursChanged() {
            view.setColors(app.colours);
        }

        function onSettingsChanged() {
            view.setFade(root.settings.fade_when_silent, root.settings.fade_delay);
            if (!app.editing && Math.round(root.boxSize) !== root.settings.size) {
                // Size changed in the settings window: resize around the centre.
                const old = root.boxSize;
                root.boxSize = root.settings.size;
                root.boxX -= (root.boxSize - old) / 2;
                root.boxY -= (root.boxSize - old) / 2;
                root.custom = true;
                root.clamp();
            }
        }

        function onEditingChanged() {
            view.setEditing(app.editing);
            if (app.editing) {
                root.updateInputArea();
                keys.forceActiveFocus();
            } else {
                root.save();
            }
        }

        function onFrameRateChanged() {
            view.setFrameRate(app.frameRate);
        }

        function onResetRequested() {
            const sw = root.boxSurface ? root.screen.width : root.width;
            const sh = root.boxSurface ? root.screen.height : root.height;
            root.custom = false;
            root.boxSize = root.settings.size;
            root.boxX = (sw - root.boxSize) / 2;
            root.boxY = (sh - root.boxSize) / 2;
            root.custom = true;
            root.clamp();
            root.updateInputArea();
            root.save();
        }
    }

    // ---- the visualizer box ----

    Item {
        id: box

        x: root.boxSurface ? 0 : root.boxX
        y: root.boxSurface ? 0 : root.boxY
        width: root.boxSize
        height: root.boxSize

        Visualizer {
            id: view

            anchors.fill: parent
            // Fades out when the music stops (the item then stops drawing) and back in when it returns.
            opacity: shown ? root.settings.opacity : 0

            Behavior on opacity {
                NumberAnimation { duration: 800; easing.type: Easing.InOutQuad }
            }

            // Advances the animation once per displayed frame (e.g. 165 times a second),
            // or at the chosen limit. A Timer is used below the display rate so Qt Quick
            // doesn't keep rendering at the display rate anyway.
            FrameAnimation {
                running: view.running && view.frameRate <= 0
                onTriggered: view.tick()
            }

            Timer {
                running: view.running && view.frameRate > 0
                interval: view.frameRate > 0 ? Math.max(1, Math.round(1000 / view.frameRate)) : 16
                repeat: true
                onTriggered: view.tick()
            }
        }

        // Edit-mode frame and controls, drawn above the web view so it gets the mouse.
        Item {
            id: editor

            anchors.fill: parent
            visible: app.editing

            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(1, 1, 1, 0.06)
                border.color: Qt.rgba(1, 1, 1, 0.8)
                border.width: 2
                radius: 10
            }

            MouseArea {
                property point start
                property point startBox

                anchors.fill: parent
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                // Window coordinates stay fixed because the surface itself never moves.
                onPressed: mouse => {
                    start = mapToItem(null, mouse.x, mouse.y);
                    startBox = Qt.point(root.boxX, root.boxY);
                }
                onPositionChanged: mouse => {
                    const p = mapToItem(null, mouse.x, mouse.y);
                    root.custom = true;
                    root.boxX = startBox.x + p.x - start.x;
                    root.boxY = startBox.y + p.y - start.y;
                    root.clamp();
                    root.updateInputArea();
                }
                onDoubleClicked: app.setEditing(false)
                onWheel: wheel => {
                    // Scroll to resize around the centre.
                    const old = root.boxSize;
                    root.custom = true;
                    root.boxSize = old + wheel.angleDelta.y / 120 * 24;
                    root.clamp();
                    root.boxX -= (root.boxSize - old) / 2;
                    root.boxY -= (root.boxSize - old) / 2;
                    root.clamp();
                    root.updateInputArea();
                }
            }

            Rectangle {
                width: 28
                height: 28
                radius: 6
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 6
                color: Qt.rgba(1, 1, 1, resizer.pressed || resizer.containsMouse ? 0.95 : 0.75)

                Text {
                    anchors.centerIn: parent
                    text: "⤡"
                    font.pixelSize: 18
                    color: "#222"
                }

                MouseArea {
                    id: resizer

                    property point start
                    property real startSize

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.SizeFDiagCursor
                    onPressed: mouse => {
                        start = mapToItem(null, mouse.x, mouse.y);
                        startSize = root.boxSize;
                    }
                    onPositionChanged: mouse => {
                        if (!pressed)
                            return;
                        const p = mapToItem(null, mouse.x, mouse.y);
                        const delta = Math.max(p.x - start.x, p.y - start.y);
                        root.custom = true;
                        root.boxSize = Math.min(startSize + delta, root.width - root.boxX, root.height - root.boxY);
                        root.clamp();
                        root.updateInputArea();
                    }
                }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 10
                width: Math.min(hint.implicitWidth + 20, parent.width - 20)
                height: hint.implicitHeight + 12
                radius: 8
                color: Qt.rgba(0, 0, 0, 0.7)

                Text {
                    id: hint

                    anchors.fill: parent
                    anchors.margins: 6
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    color: "white"
                    font.pixelSize: 13
                    text: "Drag to move · corner or scroll to resize\nDouble-click or Esc when done"
                }
            }
        }
    }

    Item {
        id: keys

        focus: app.editing
        Keys.onEscapePressed: app.setEditing(false)
        Keys.onReturnPressed: app.setEditing(false)
        Keys.onEnterPressed: app.setEditing(false)
    }
}
