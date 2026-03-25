"""P5: Translation completeness and correctness."""
from unittest.mock import MagicMock

from translations import _translations, get_translator, detect_locale, SUPPORTED_LOCALES


class TestTranslationCompleteness:
    def test_all_keys_have_all_languages(self):
        """Every translation key must exist in all 7 supported languages."""
        # Collect all keys from all locales
        all_keys = set()
        for lang_data in _translations.values():
            all_keys.update(lang_data.keys())

        for key in all_keys:
            for lang in SUPPORTED_LOCALES:
                assert key in _translations[lang], \
                    f"Key '{key}' missing in language '{lang}'"


class TestCallableTranslations:
    def test_callable_translations_work(self):
        """Plural translations should work with n=1,2,5."""
        for lang in SUPPORTED_LOCALES:
            t = get_translator(lang)
            for n in [1, 2, 5]:
                result = t('nights_word', n=n)
                assert isinstance(result, str) and len(result) > 0, \
                    f"nights_word({n}) failed for lang={lang}"
                result = t('results_word', n=n)
                assert isinstance(result, str) and len(result) > 0, \
                    f"results_word({n}) failed for lang={lang}"

    def test_russian_plurals(self):
        """Russian plural rules: 1=ночь, 2-4=ночи, 5+=ночей, 11-14=ночей."""
        t = get_translator('ru')
        assert 'ночь' in t('nights_word', n=1)
        assert 'ночи' in t('nights_word', n=2)
        assert 'ночей' in t('nights_word', n=5)
        assert 'ночей' in t('nights_word', n=11)  # 11-14 special case
        assert t('nights_word', n=21) == 'ночь'     # 21 → like 1

    def test_nomad_stay_plurals(self):
        """nomad_stay works for all languages."""
        for lang in SUPPORTED_LOCALES:
            t = get_translator(lang)
            for n in [1, 2, 5]:
                result = t('nomad_stay', n=n)
                assert str(n) in result, f"nomad_stay({n}) for {lang} should contain {n}, got '{result}'"


def _mock_request(query_params=None, headers=None):
    req = MagicMock()
    req.query_params = query_params or {}
    req.headers = headers or {}
    return req


class TestDetectLocale:
    def test_lang_param_priority(self):
        req = _mock_request(query_params={'lang': 'es'}, headers={'Accept-Language': 'fr'})
        assert detect_locale(req) == 'es'

    def test_accept_language_parsing(self):
        req = _mock_request(headers={'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8'})
        assert detect_locale(req) == 'it'

    def test_unsupported_falls_to_default(self):
        req = _mock_request(query_params={'lang': 'zh'}, headers={'Accept-Language': 'zh-CN'})
        assert detect_locale(req) == 'en'

    def test_empty_header_defaults_to_en(self):
        req = _mock_request()
        assert detect_locale(req) == 'en'


class TestTranslatorKwargs:
    def test_format_substitution(self):
        t = get_translator('en')
        result = t('error_search', e='timeout')
        assert 'timeout' in result

    def test_format_with_n_in_string(self):
        t = get_translator('en')
        result = t('selected_count', n=5)
        assert '5' in result

    def test_no_kwargs_returns_template(self):
        t = get_translator('en')
        result = t('error_search')
        assert '{e}' in result


class TestTranslatorFallback:
    def test_missing_key_returns_key(self):
        t = get_translator('en')
        assert t('nonexistent_key_xyz') == 'nonexistent_key_xyz'

    def test_unsupported_lang_uses_default(self):
        t = get_translator('zh')
        result = t('error_search', e='x')
        assert 'x' in result
