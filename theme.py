"""
Color palettes, dark/light/system mode resolution, and the live COLORS dict.

COLORS is a module-level dict that gets mutated in place (via .clear()/.update())
rather than reassigned, so every other module that does `from theme import COLORS`
sees updates immediately without needing to re-import anything.
"""

import winreg


def shade(hex_color: str, factor: float) -> str:
    """Lighten (factor > 1) or darken (factor < 1) a hex color."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


# ============================================================
# PALETTES — 5 hex swatches each, ordered lightest -> darkest.
# "Original" preserves the first palette. The rest are the first
# 10 named combinations from Figma's "100 color combinations"
# resource-library article, approximated from the color names/
# descriptions in that article's text (the swatches on that page
# are images, not machine-readable hex
# ============================================================
PALETTES = {
    "Original": ["#D4EAC8", "#CAD49D", "#56A3A6", "#3E7376", "#484538"],
    "Stormy Morning":    ["#D7DEE4", "#AFC0CC", "#7D93A3", "#4F6577", "#2E3C48"],
    "Mossy Hollow":      ["#E4E6D3", "#C7CBA0", "#9AA35E", "#6E7A3E", "#3F471F"],
    "Blue Eclipse":      ["#C9D2E0", "#8FA3C4", "#4C6491", "#2A3A5C", "#10182B"],
    "Lush Forest":       ["#DCE8DA", "#A9C7A2", "#5E8F57", "#386B39", "#1B3A1D"],
    "Green Juice":       ["#DFF3D8", "#A9E098", "#4CAF50", "#2E7D32", "#123D14"],
    "Chili Spice":       ["#F5D6CE", "#E8A190", "#D2452B", "#9C2A18", "#4E140C"],
    "Chocolate Truffle": ["#F1E4CF", "#D8B98A", "#B98950", "#7A5230", "#3B2416"],
    "Ink Wash":          ["#F1EFE9", "#CFCFC9", "#9A9A94", "#55554F", "#1C1C1A"],
    "Golden Taupe":      ["#F2E9D8", "#D9C39C", "#B99B6B", "#8C765A", "#4F4232"],
    "Wisteria Bloom":    ["#EFE3F5", "#C9A8DE", "#9B6BC0", "#6B3E93", "#3B1E52"],
}


def resolve_colors(mode: str, palette_name: str) -> dict:
    """Build a full COLORS dict from a mode (dark/light) and a named palette."""
    light, secondary, accent, dim_c, dark = PALETTES.get(palette_name, PALETTES["Original"])
    if mode == "light":
        bg = shade(light, 1.05)
        card = shade(light, 0.94)
        card2 = shade(light, 0.88)
        text = "#232323"
        text_dim = shade(dark, 1.7)
    else:  # dark
        bg = shade(dark, 0.90)
        card = shade(dark, 1.15)
        card2 = shade(dark, 1.40)
        text = "#000"
        text_dim = light
    return {
        "bg": bg, "card": card, "card2": card2,
        "accent": accent, "accent2": secondary,
        "light": light, "sky": dim_c,
        "text": text, "text_dim": text_dim,
        "success": secondary,
        "warning": "#E07A5F",  # not palette-derived — kept distinct so alerts stay legible in every palette
    }


def get_system_theme() -> str:
    """Read Windows' current light/dark app theme setting."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if value == 1 else "dark"
    except Exception:
        return "dark"


COLORS = resolve_colors("dark", "Original")  # placeholder; each app instance re-resolves this in __init__
