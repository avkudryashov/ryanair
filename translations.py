"""i18n translations for the web UI — loads from locales/*.json."""
import json
import os

SUPPORTED_LOCALES = {
    'en': 'English',
    'es': 'Español',
    'it': 'Italiano',
    'fr': 'Français',
    'pt': 'Português',
    'de': 'Deutsch',
    'ru': 'Русский',
}

DEFAULT_LOCALE = 'en'

# OG locale mapping
OG_LOCALES = {
    'en': 'en_US', 'es': 'es_ES', 'it': 'it_IT',
    'fr': 'fr_FR', 'pt': 'pt_PT', 'de': 'de_DE', 'ru': 'ru_RU',
}

# ── Load translations from JSON ──

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'locales')
_translations: dict[str, dict] = {}


def _load_translations():
    """Load all locale JSON files into memory."""
    for lang in SUPPORTED_LOCALES:
        path = os.path.join(_LOCALES_DIR, f'{lang}.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                _translations[lang] = json.load(f)
        except FileNotFoundError:
            _translations[lang] = {}


_load_translations()


# ── Plural rules (ICU-like) ──

def _plural_form(n: int, lang: str) -> str:
    """Return ICU plural category for n in the given language."""
    if lang == 'ru':
        if 11 <= n % 100 <= 19:
            return 'other'
        if n % 10 == 1:
            return 'one'
        if 2 <= n % 10 <= 4:
            return 'few'
        return 'other'
    return 'one' if n == 1 else 'other'


# ── Translator ──

def get_translator(lang):
    """Returns a translation function for the given locale."""
    if lang not in SUPPORTED_LOCALES:
        lang = DEFAULT_LOCALE

    locale_data = _translations.get(lang, {})
    fallback_data = _translations.get(DEFAULT_LOCALE, {})

    def _(key, **kwargs):
        text = locale_data.get(key, fallback_data.get(key, key))

        # Plural dict: {"one": "...", "few": "...", "other": "..."}
        if isinstance(text, dict):
            n = kwargs.get('n', 1)
            if isinstance(n, int):
                form = _plural_form(n, lang)
                result = text.get(form, text.get('other', ''))
                if '{n}' in result:
                    result = result.replace('{n}', str(n))
                return result
            return text.get('other', '')

        # String with format placeholders
        if kwargs and isinstance(text, str):
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                return text

        return text

    return _


def detect_locale(request):
    """Detect locale from ?lang= param or Accept-Language header."""
    # 1. Explicit ?lang= parameter
    params = getattr(request, 'query_params', None) or getattr(request, 'args', {})
    lang = params.get('lang', '').strip().lower()
    if lang in SUPPORTED_LOCALES:
        return lang

    # 2. Accept-Language header
    accept = request.headers.get('Accept-Language', '')
    for part in accept.split(','):
        code = part.split(';')[0].strip().lower()
        short = code[:2]
        if short in SUPPORTED_LOCALES:
            return short

    return DEFAULT_LOCALE
