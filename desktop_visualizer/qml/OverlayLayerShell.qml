import QtQuick
import org.kde.layershell as LayerShell

// The overlay as a layer-shell surface (KDE Plasma, Hyprland, Sway, ...), so the compositor
// keeps it above (or, for "Desktop only", below) normal windows.
// Requires QT_WAYLAND_SHELL_INTEGRATION=layer-shell.
//
// Outside edit mode the surface is only as big as the visualizer box, so the compositor
// doesn't have to blend a full-screen transparent surface every frame. Edit mode needs the
// full screen so the box can be dragged and resized inside it.
Overlay {
    id: shell

    shrinkable: true
    width: boxSurface ? boxSize : screen.width
    height: boxSurface ? boxSize : screen.height

    LayerShell.Window.scope: "desktop-visualizer"
    // "bottom" sits on the desktop: above the wallpaper, below every window. While editing,
    // go on top so the box can still be grabbed when windows cover the desktop.
    LayerShell.Window.layer: app.editing ? LayerShell.Window.LayerTop
                           : settings.layer === "overlay" ? LayerShell.Window.LayerOverlay
                           : settings.layer === "bottom" ? LayerShell.Window.LayerBottom
                           : LayerShell.Window.LayerTop
    LayerShell.Window.anchors: boxSurface
        ? (LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft)
        : (LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
           | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight)
    LayerShell.Window.margins: boxSurface
        ? ({ left: Math.round(boxX), top: Math.round(boxY), right: 0, bottom: 0 })
        : ({ left: 0, top: 0, right: 0, bottom: 0 })
    LayerShell.Window.keyboardInteractivity: app.editing ? LayerShell.Window.KeyboardInteractivityOnDemand
                                                         : LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.exclusionZone: 0
}
