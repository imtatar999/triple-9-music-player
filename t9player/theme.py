"""Themes: colour palettes, fonts and small details, plus the Qt stylesheet.

A theme is applied once at start-up (theme.apply) before any window is built;
switching themes restarts the player. Widgets read the module-level names
(BG, RED, TEXT ...) at paint time, so they always follow the active theme.
"""

import os

# names kept from the first version: RED* = the theme's accent colour
THEMES = {
    "999": dict(
        label="999", hint="Black with dark red - the original look",
        BG="#09090b", BG_ALT="#0e0e11", SIDEBAR="#0c0c0f", PANEL="#131317", RAISED="#1a1a1f",
        HOVER="#1f1f25", BORDER="#1f1f25", RED="#d4142b", RED_BRIGHT="#ff3b47", RED_DARK="#6b0a14",
        RED_DEEP="#2a0509", ACCENT2="#ff3b47", TEXT="#ececef", DIM="#8d8d96", FAINT="#56565e",
        ON_ACCENT="#ffffff", SCROLL="#2a2a31", BAR_TOP="#0d0d10", BAR_BOTTOM="#070708",
        FONT="Segoe UI", TITLE_FONT="Segoe UI", TITLE_WEIGHT=700, TITLE_CASE="none", TITLE_SCALE=1.0,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#d9a3a8", LYR_PAST="#6e4a4f",
        LYR_BG=("#1c0408", "#0b0909", "#050505"), PLACEHOLDER=("#2a070c", "#0d0b0d"),
        BRAND="logo", LOGO="06_red_blood", DECOR="999", SECRET=False),
    "gbgr": dict(
        label="Goodbye & Good Riddance", hint="Sky blue, handwriting and the blue car on the road",
        BG="#07111b", BG_ALT="#0a1623", SIDEBAR="#08131f", PANEL="#0f1e2d", RAISED="#142638",
        HOVER="#183047", BORDER="#16283a", RED="#2b9fd8", RED_BRIGHT="#55c4f5", RED_DARK="#14506f",
        RED_DEEP="#0d2a3f", ACCENT2="#e8384f", TEXT="#eef3f8", DIM="#8ea3b8", FAINT="#4f6478",
        ON_ACCENT="#ffffff", SCROLL="#1d3448", BAR_TOP="#0b1826", BAR_BOTTOM="#060d15",
        FONT="Segoe UI", TITLE_FONT="Ink Free", TITLE_WEIGHT=700, TITLE_CASE="none", TITLE_SCALE=1.15,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#9fd4f2", LYR_PAST="#4b6a82",
        LYR_BG=("#0d3550", "#081624", "#04080d"), PLACEHOLDER=("#123a55", "#0a1520"),
        BRAND="logo", LOGO="07_ice_blue", DECOR="gbgr", SECRET=False),
    "wod": dict(
        label="WRLD On Drugs", hint="Purple drip and the melting planet",
        BG="#0f0a14", BG_ALT="#140d1a", SIDEBAR="#110b17", PANEL="#1a1222", RAISED="#21172b",
        HOVER="#2a1d36", BORDER="#251a30", RED="#b65cff", RED_BRIGHT="#d38bff", RED_DARK="#5a2a80",
        RED_DEEP="#2a1440", ACCENT2="#ffcf3f", TEXT="#f3eefa", DIM="#a596b6", FAINT="#5e5270",
        ON_ACCENT="#ffffff", SCROLL="#33254a", BAR_TOP="#150e1c", BAR_BOTTOM="#0a060d",
        FONT="Segoe UI", TITLE_FONT="Segoe UI Black", TITLE_WEIGHT=900, TITLE_CASE="none", TITLE_SCALE=1.0,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#e3b8ff", LYR_PAST="#6b5280",
        LYR_BG=("#3a1a52", "#140c1c", "#07040a"), PLACEHOLDER=("#3a1a52", "#120b18"),
        BRAND="logo", LOGO="10_lean_drip", DECOR="wod", SECRET=False),
    "tpne": dict(
        label="The Party Never Ends", hint="Galaxy purple, rainbow flowers and the smiling planet",
        BG="#0e0820", BG_ALT="#130a2a", SIDEBAR="#110925", PANEL="#1b1036", RAISED="#231544",
        HOVER="#2c1b55", BORDER="#2a1a4e", RED="#ff3fc8", RED_BRIGHT="#ff7fdc", RED_DARK="#7a1a66",
        RED_DEEP="#2e0b33", ACCENT2="#7dff4a", TEXT="#fbf6ff", DIM="#b9a8d6", FAINT="#6a5a8c",
        ON_ACCENT="#ffffff", SCROLL="#3b2766", BAR_TOP="#140b2c", BAR_BOTTOM="#0a0618",
        FONT="Segoe UI", TITLE_FONT="Kaushan Script", TITLE_WEIGHT=400, TITLE_CASE="none", TITLE_SCALE=1.15,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#ffb0ea", LYR_PAST="#6c5a92",
        LYR_BG=("#3a1466", "#1a0c38", "#0a0618"), PLACEHOLDER=("#3a1466", "#130a2a"),
        BRAND="logo", LOGO="04_marble_neon", DECOR="tpne", SECRET=False),
    "outsiders": dict(
        label="Outsiders", hint="Black and white sketch: doves, sparkles and the boy with the 999 bag",
        BG="#08080a", BG_ALT="#0c0c0e", SIDEBAR="#0a0a0c", PANEL="#141416", RAISED="#1b1b1e",
        HOVER="#232327", BORDER="#26262a", RED="#f2f2f2", RED_BRIGHT="#ffffff", RED_DARK="#6a6a70",
        RED_DEEP="#26262a", ACCENT2="#bdbdbd", TEXT="#f1f1f3", DIM="#9a9aa2", FAINT="#55555c",
        SCROLL="#2a2a2e", BAR_TOP="#0d0d0f", BAR_BOTTOM="#050506", ON_ACCENT="#000000",
        FONT="Segoe UI", TITLE_FONT="I KNOW A GHOST", TITLE_WEIGHT=400, TITLE_CASE="none", TITLE_SCALE=1.25,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#a9a9b0", LYR_PAST="#4c4c52",
        LYR_BG=("#1a1a1e", "#0b0b0d", "#030304"), PLACEHOLDER=("#1e1e22", "#0a0a0c"),
        BRAND="logo", LOGO="01_classic_black_white", DECOR="outsiders", SECRET=False),
    "drfl": dict(
        label="Death Race for Love", hint="Fire, chrome and race cars",
        BG="#0c0a09", BG_ALT="#110e0c", SIDEBAR="#0e0b0a", PANEL="#17120f", RAISED="#1f1814",
        HOVER="#2a1f18", BORDER="#2a201a", RED="#ff5a1f", RED_BRIGHT="#ff8a3d", RED_DARK="#7a260a",
        RED_DEEP="#2e1006", ACCENT2="#d9d4cc", TEXT="#ece8e3", DIM="#a39a90", FAINT="#5e554d",
        SCROLL="#3a2b22", BAR_TOP="#14100d", BAR_BOTTOM="#080605", ON_ACCENT="#ffffff",
        FONT="Segoe UI", TITLE_FONT="Dream MMA", TITLE_WEIGHT=400, TITLE_CASE="lower_ascii", TITLE_SCALE=0.95,
        LYR_ACTIVE="#ffffff", LYR_UPCOMING="#ffb27a", LYR_PAST="#6b4a38",
        LYR_BG=("#3a1206", "#140c08", "#060404"), PLACEHOLDER=("#3a1206", "#0e0a08"),
        BRAND="logo", LOGO="08_gold", DECOR="drfl", SECRET=False),
    "lnd": dict(
        label="Legends Never Die", hint="Sunset pink, poppies, butterflies and falling stars",
        BG="#140b1a", BG_ALT="#1a0e21", SIDEBAR="#170c1e", PANEL="#22122b", RAISED="#2b1735",
        HOVER="#341c40", BORDER="#2e1838", RED="#ff6f9f", RED_BRIGHT="#ffa0c2", RED_DARK="#8a2f5a",
        RED_DEEP="#3a1230", ACCENT2="#ff9a3d", TEXT="#fff3ec", DIM="#c9abbc", FAINT="#735a6d",
        ON_ACCENT="#ffffff", SCROLL="#43284f", BAR_TOP="#1b0f22", BAR_BOTTOM="#0f0814",
        FONT="Segoe UI", TITLE_FONT="Dancing Script", TITLE_WEIGHT=600, TITLE_CASE="none", TITLE_SCALE=1.25,
        LYR_ACTIVE="#fff6e8", LYR_UPCOMING="#ffb3c9", LYR_PAST="#7a5670",
        LYR_BG=("#5a1f45", "#2a1230", "#120a18"), PLACEHOLDER=("#5a1f45", "#1a0e21"),
        BRAND="logo", LOGO="05_purple_pink", DECOR="lnd", SECRET=False),
}
ORDER = ("999", "gbgr", "wod", "drfl", "lnd", "tpne", "outsiders")
NAME = "999"
# the active theme's values (filled by apply(); declared here for readers and linters)
_D = THEMES["999"]
BG, BG_ALT, SIDEBAR, PANEL, RAISED = _D["BG"], _D["BG_ALT"], _D["SIDEBAR"], _D["PANEL"], _D["RAISED"]
HOVER, BORDER, SCROLL, BAR_TOP, BAR_BOTTOM = _D["HOVER"], _D["BORDER"], _D["SCROLL"], _D["BAR_TOP"], _D["BAR_BOTTOM"]
RED, RED_BRIGHT, RED_DARK, RED_DEEP, ACCENT2 = _D["RED"], _D["RED_BRIGHT"], _D["RED_DARK"], _D["RED_DEEP"], _D["ACCENT2"]
TEXT, DIM, FAINT = _D["TEXT"], _D["DIM"], _D["FAINT"]
FONT, TITLE_FONT, TITLE_WEIGHT, TITLE_CASE, TITLE_SCALE = (
    _D["FONT"], _D["TITLE_FONT"], _D["TITLE_WEIGHT"], _D["TITLE_CASE"], _D["TITLE_SCALE"])
ON_ACCENT = _D["ON_ACCENT"]
LYR_ACTIVE, LYR_UPCOMING, LYR_PAST, LYR_BG = _D["LYR_ACTIVE"], _D["LYR_UPCOMING"], _D["LYR_PAST"], _D["LYR_BG"]
PLACEHOLDER, BRAND, LOGO, DECOR, SECRET = (
    _D["PLACEHOLDER"], _D["BRAND"], _D["LOGO"], _D["DECOR"], _D["SECRET"])
label, hint = _D["label"], _D["hint"]


def apply(name):
    """Activate a theme (call before building any window)."""
    global NAME
    name = name if name in THEMES else "999"
    NAME = name
    for key, value in THEMES[name].items():
        globals()[key] = value
    return name


def load_fonts():
    """Register the display fonts shipped in assets/fonts (works without installing them)."""
    from PySide6.QtGui import QFontDatabase
    from . import paths
    folder = os.path.join(paths.ASSETS_DIR, "fonts")
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(folder, name))


def visible_themes(theme_keys):
    """The regular themes in album order, then the unlocked secret ones in the order they were unlocked."""
    return list(ORDER) + [n for n in (theme_keys or {}) if n in THEMES and n not in ORDER]


# ---------------------------------------------------------------- secret themes (see vault.py)
PHRASES = {}    # theme -> {English text: the theme's own wording}
EXTRAS = {}     # theme -> extra texts (home page lines, greetings, toasts ...)
FILES = {}      # file name -> bytes of pictures and fonts that come with unlocked themes
_vault = None


def _the_vault():
    global _vault
    if _vault is None:
        from . import vault
        _vault = vault.load() or {}
    return _vault


def register(payload):
    """Make an opened secret theme available: palette, texts, translations, pictures and fonts."""
    import base64
    name = payload["name"]
    t = dict(payload["theme"])
    t["LYR_BG"], t["PLACEHOLDER"] = tuple(t["LYR_BG"]), tuple(t["PLACEHOLDER"])
    t["SECRET"] = True
    THEMES[name] = t
    PHRASES[name] = dict(payload.get("phrases", {}))
    EXTRAS[name] = dict(payload.get("extras", {}))
    from . import i18n
    i18n.add_translations(payload.get("pl", {}))
    for fname, data in payload.get("files", {}).items():
        FILES[fname] = base64.b64decode(data)
        if fname.lower().endswith((".ttf", ".otf")):
            try:
                from PySide6.QtCore import QByteArray
                from PySide6.QtGui import QFontDatabase
                QFontDatabase.addApplicationFontFromData(QByteArray(FILES[fname]))
            except Exception:
                pass
    return name


def open_saved(theme_keys):
    """Register the secret themes whose keys are in the settings; returns {name: key} that still open."""
    opened = {}
    for name, key in (theme_keys or {}).items():
        from . import vault
        payload = vault.open_with_key(key, _the_vault())
        if payload is not None:
            opened[register(payload)] = key
    return opened


def try_code(code, theme_keys):
    """(theme, now_visible, new theme_keys) for a typed code; theme is None for a wrong code.
    The same code shows a secret theme and, typed again, hides it."""
    from . import vault
    keys = dict(theme_keys or {})
    key, payload = vault.unlock(code, _the_vault())
    if payload is None:
        return None, False, keys
    name = register(payload)
    if name in keys:
        keys.pop(name)
        return name, False, keys
    keys[name] = key
    return name, True, keys


def extra(key, default=None):
    """An extra text of the active theme (None for regular themes)."""
    return EXTRAS.get(NAME, {}).get(key, default)





def say(text, **values):
    """tr() with the active theme's own wording, if it has one."""
    from .i18n import tr
    return tr(PHRASES.get(NAME, {}).get(text, text), **values)


def title_css(size):
    """CSS for big headings in the active theme's display font."""
    return (f'font-family: "{TITLE_FONT}"; font-size: {int(size * TITLE_SCALE)}px; '
            f"font-weight: {TITLE_WEIGHT};")


_ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


# fonts with every Polish letter; the decorative theme fonts (Old London, I KNOW A GHOST ...) lack them
FULL_FONTS = ("Segoe UI", "Segoe UI Black", "Consolas")


def title_text(text, case=None, font=None):
    """Headings in the theme's style (Dream MMA only has lower-case letters, for example).

    Decorative fonts have no Polish letters, so "Najczęściej" is written "Najczesciej" there.
    """
    case = case or TITLE_CASE
    if (font or TITLE_FONT) not in FULL_FONTS:
        text = text.translate(_ASCII)
    if case == "upper":
        return text.upper()
    if case == "lower_ascii":
        return text.translate(_ASCII).lower()
    return text


def _asset(name):
    from . import paths
    return os.path.join(paths.ASSETS_DIR, name).replace(os.sep, "/")


_SVG_PATHS = {
    "check": "M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
    "sort_up": "M7 14l5-5 5 5z",
    "sort_down": "M7 10l5 5 5-5z",
    "combo_down": "M7 10l5 5 5-5z",
}


def _themed_svg(name, color):
    """Small SVG in the theme's colour for the stylesheet (written once to the data folder)."""
    from . import paths
    folder = os.path.join(paths.DATA_DIR, "theme_assets")
    path = os.path.join(folder, f"{name}_{color.lstrip('#')}.svg")
    if not os.path.isfile(path):
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                             f'<path fill="{color}" d="{_SVG_PATHS[name]}"/></svg>')
        except OSError:
            return _asset(f"{name}.svg")
    return path.replace(os.sep, "/")


def stylesheet():
    return f"""
* {{
    font-family: "{FONT}";
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog, #Root {{
    background: {BG};
}}
QToolTip {{
    background: {RAISED};
    color: {TEXT};
    border: 1px solid {RED_DARK};
    padding: 5px 8px;
    border-radius: 6px;
    font-size: 12px;
}}
QLabel {{ background: transparent; }}
QLabel#Dim {{ color: {DIM}; }}
QLabel#H1 {{ {title_css(26)} }}
QLabel#H2 {{ font-size: 15px; font-weight: 600; }}
QLabel#Badge {{
    color: {RED_BRIGHT};
    background: {RED_DEEP};
    border: 1px solid {RED_DARK};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}}
#Sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
#PlayerBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BAR_TOP}, stop:1 {BAR_BOTTOM});
    border-top: 1px solid {BORDER};
}}
QListWidget#Nav {{
    background: transparent;
    border: none;
    font-size: 13px;
}}
QListWidget#Nav::item {{
    padding: 7px 10px;
    border-radius: 6px;
    margin: 1px 6px;
    color: {DIM};
}}
QListWidget#Nav::item:hover {{ background: {HOVER}; color: {TEXT}; }}
QListWidget#Nav::item:selected {{
    background: {RED_DEEP};
    color: {TEXT};
    border-left: 3px solid {RED};
}}
QLabel#NavHeader {{
    color: {FAINT};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 12px 16px 4px 16px;
}}
QLineEdit {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 16px;
    padding: 6px 12px;
    selection-background-color: {RED_DARK};
    font-size: 13px;
}}
QLineEdit:focus {{ border: 1px solid {RED_DARK}; }}
QTableView {{
    background: transparent;
    alternate-background-color: transparent;
    border: none;
    gridline-color: transparent;
    selection-background-color: {RED_DEEP};
    selection-color: {TEXT};
    font-size: 13px;
}}
QTableView::item {{ border: none; padding: 0 6px; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent;
    color: {DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    font-size: 12px;
}}
QHeaderView::section:hover {{ color: {TEXT}; }}
QHeaderView::up-arrow {{ image: url("{_themed_svg('sort_up', RED)}"); width: 14px; height: 14px; subcontrol-position: center right; padding-right: 4px; }}
QHeaderView::down-arrow {{ image: url("{_themed_svg('sort_down', RED)}"); width: 14px; height: 14px; subcontrol-position: center right; padding-right: 4px; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {SCROLL}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {RED_DARK}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{
    background: {RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {RED_DEEP}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QPushButton {{
    background: {RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {HOVER}; border-color: {RED_DARK}; }}
QPushButton:pressed {{ background: {RED_DEEP}; }}
QPushButton#Primary {{ background: {RED}; border-color: {RED}; font-weight: 600; color: {ON_ACCENT}; }}
QPushButton#Primary:hover {{ background: {RED_BRIGHT}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover {{ border-color: {RED_DARK}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{_themed_svg('combo_down', DIM)}"); width: 16px; height: 16px; }}
QComboBox QAbstractItemView {{
    background: {RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {RED_DEEP};
}}
QCheckBox {{ spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {FAINT}; background: {PANEL};
}}
QCheckBox::indicator:checked {{ background: {RED}; border-color: {RED}; image: url("{_themed_svg('check', ON_ACCENT)}"); }}
QCheckBox::indicator:hover {{ border-color: {RED_BRIGHT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; background: {BG_ALT}; }}
QTabBar::tab {{
    background: transparent; color: {DIM};
    padding: 8px 16px; border: none; font-size: 13px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {RED}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QListWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QListWidget::item {{ padding: 6px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {RED_DEEP}; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QSlider::groove:horizontal {{ height: 4px; background: {SCROLL}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {RED}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}}
QProgressBar {{
    background: {PANEL}; border: none; border-radius: 2px; height: 4px; text-align: center;
}}
QProgressBar::chunk {{ background: {RED}; border-radius: 2px; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QTabWidget QScrollArea > QWidget > QWidget {{ background: {BG_ALT}; }}
"""
