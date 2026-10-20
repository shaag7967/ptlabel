"""Translations via gettext.

Source strings are English; ``locale/<lang>/LC_MESSAGES/ptlabel.mo`` holds the translations.
The language is taken from the ``language`` setting, then from the environment (LANGUAGE,
LC_ALL, LC_MESSAGES, LANG) and on Windows from the user's display language.
"""

from __future__ import annotations

import gettext
import locale
import os
import sys
from pathlib import Path

from . import config

DOMAIN = "ptlabel"
LOCALE_DIR = Path(__file__).parent / "locale"


def _system_languages() -> list[str]:
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return [lang for lang in value.split(":") if lang]
    if sys.platform == "win32":
        try:
            import ctypes
            name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            if name:
                return [name]
        except (AttributeError, OSError):
            pass
    return []


def requested_languages() -> list[str]:
    configured = str(config.load().get("language") or "").strip()
    return [configured] if configured else _system_languages()


def translation(languages: list[str] | None = None) -> gettext.NullTranslations:
    return gettext.translation(DOMAIN, LOCALE_DIR, languages=languages or ["en"], fallback=True)


_translation = translation(requested_languages())
tr = _translation.gettext
ntr = _translation.ngettext


def language() -> str:
    """Language code of the active translation, e.g. "de"; "en" for the untranslated source."""
    return (_translation.info().get("language") or "en").split("_")[0]
