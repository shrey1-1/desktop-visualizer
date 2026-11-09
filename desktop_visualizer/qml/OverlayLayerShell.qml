import QtQuick
import org.kde.layershell as LayerShell

// The overlay as a layer-shell surface (KDE Plasma, Hyprland, Sway, ...), so the compositor
// keeps it above normal windows. Requires QT_WAYLAND_SHELL_INTEGRATION=layer-shell.
Overlay {
    LayerShell.Window.scope: "desktop-visualizer"
    LayerShell.Window.layer: settings.layer === "overlay" ? LayerShell.Window.LayerOverlay : LayerShell.Window.LayerTop
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                               | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.keyboardInteractivity: app.editing ? LayerShell.Window.KeyboardInteractivityOnDemand
                                                         : LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.exclusionZone: 0
}
