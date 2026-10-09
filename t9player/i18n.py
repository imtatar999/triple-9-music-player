"""Translations. English text is the key; Polish lives in i18n_pl.py.

    tr("Added {n} songs to the queue", n=3)
    songs(5)  ->  "5 songs" / "5 utworów"
"""

LANGUAGES = (("auto", "Automatic (system language)"), ("en", "English"), ("pl", "Polski"))
_lang = "en"
_table = {}
_extra_pl = {}      # translations that come with unlocked secret themes


def set_language(code):
    """'auto' | 'en' | 'pl'. Returns the language actually used."""
    global _lang, _table
    if code not in ("en", "pl"):
        code = _system_language()
    _lang = code
    if code == "pl":
        from .i18n_pl import PL
        _table = {**PL, **_extra_pl}
    else:
        _table = {}
    return code


def add_translations(pl):
    """Polish texts of a secret theme (they are not in i18n_pl.py)."""
    _extra_pl.update(pl or {})
    if _lang == "pl":
        _table.update(pl or {})


def language():
    return _lang


def _system_language():
    try:
        from PySide6.QtCore import QLocale
        if QLocale.system().language() == QLocale.Polish:
            return "pl"
    except Exception:
        pass
    return "en"


def tr(text, **values):
    out = _table.get(text, text)
    if values:
        try:
            return out.format(**values)
        except (KeyError, IndexError, ValueError):
            return text.format(**values)
    return out


def plural(n, one, few, many):
    """Polish plural forms; English uses `one` / `many` (pass the English words)."""
    if _lang != "pl":
        return one if n == 1 else many
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def songs(n):
    return f"{n} " + (plural(n, "utwór", "utwory", "utworów") if _lang == "pl" else ("song" if n == 1 else "songs"))


def albums(n):
    return f"{n} " + (plural(n, "album", "albumy", "albumów") if _lang == "pl" else ("album" if n == 1 else "albums"))


def times(n):
    """'7 plays' / '7 odtworzeń'."""
    return f"{n} " + (plural(n, "odtworzenie", "odtworzenia", "odtworzeń") if _lang == "pl" else ("play" if n == 1 else "plays"))


def duration_long(seconds):
    """'47 min 30 s' / '2 h 5 min' (Spotify style album length)."""
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    return f"{m} min {s} s"
