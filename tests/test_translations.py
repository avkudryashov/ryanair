"""P5: Translation completeness and correctness."""
from translations import TRANSLATIONS, get_translator, SUPPORTED_LOCALES


class TestTranslationCompleteness:
    def test_all_keys_have_all_languages(self):
        """Every translation key must have all 7 supported languages."""
        langs = set(SUPPORTED_LOCALES.keys())
        for key, value in TRANSLATIONS.items():
            if isinstance(value, dict):
                missing = langs - set(value.keys())
                assert not missing, f"Key '{key}' missing languages: {missing}"


class TestCallableTranslations:
    def test_callable_translations_work(self):
        """Lambda translations should work with n=1,2,5."""
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
        """nomad_stay lambda works for all languages."""
        for lang in SUPPORTED_LOCALES:
            t = get_translator(lang)
            for n in [1, 2, 5]:
                result = t('nomad_stay', n=n)
                assert str(n) in result, f"nomad_stay({n}) for {lang} should contain {n}, got '{result}'"
