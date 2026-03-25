"""Тесты кэширования: diskcache, SWR, persistence."""
import time
import diskcache
import pytest


class TestCacheGetSet:
    """Базовые операции кэша."""

    def test_cache_set_and_get_fresh(self, searcher):
        key = "test:fresh"
        searcher._cache.set(key, {"data": 42}, stale_ttl=3600)

        data, is_stale = searcher._cache.get(key, fresh_ttl=60, stale_ttl=3600)
        assert data == {"data": 42}
        assert is_stale is False

    def test_cache_miss_returns_none(self, searcher):
        data, is_stale = searcher._cache.get("nonexistent", 60, 3600)
        assert data is None
        assert is_stale is False

    def test_cache_stale_after_fresh_ttl(self, searcher):
        key = "test:stale"
        searcher._cache.set(key, "value", stale_ttl=3600)
        # Подменяем timestamp чтобы данные стали stale
        raw_data, ts = searcher._cache.disk.get(key)
        searcher._cache.disk.set(key, (raw_data, time.time() - 120), expire=3600)
        # Очищаем L1 чтобы тест проверял именно L2 SWR логику
        searcher._cache.l1.clear()

        data, is_stale = searcher._cache.get(key, fresh_ttl=60, stale_ttl=3600)
        assert data == "value"
        assert is_stale is True

    def test_cache_expired_after_stale_ttl(self, searcher):
        key = "test:expired"
        searcher._cache.set(key, "value", stale_ttl=3600)
        raw_data, ts = searcher._cache.disk.get(key)
        searcher._cache.disk.set(key, (raw_data, time.time() - 7200), expire=3600)
        searcher._cache.l1.clear()

        data, is_stale = searcher._cache.get(key, fresh_ttl=60, stale_ttl=3600)
        assert data is None

    def test_cache_persists_on_disk(self, tmp_cache_dir):
        """Кэш переживает пересоздание объекта."""
        cache1 = diskcache.Cache(tmp_cache_dir)
        cache1.set("persist_key", ("hello", time.time()), expire=3600)
        cache1.close()

        cache2 = diskcache.Cache(tmp_cache_dir)
        raw = cache2.get("persist_key")
        cache2.close()
        assert raw is not None
        assert raw[0] == "hello"


class TestCacheKey:
    def test_cache_key_deterministic(self, searcher):
        k1 = searcher._cache.key("flights", "VLC", "BGY", "2026-05-01", 2)
        k2 = searcher._cache.key("flights", "VLC", "BGY", "2026-05-01", 2)
        assert k1 == k2

    def test_cache_key_different_params(self, searcher):
        k1 = searcher._cache.key("flights", "VLC", "BGY", "2026-05-01", 2)
        k2 = searcher._cache.key("flights", "VLC", "MXP", "2026-05-01", 2)
        assert k1 != k2


class TestCacheStats:
    def test_cache_stats(self, searcher):
        stats = searcher._cache.stats()
        assert 'size' in stats
        assert 'volume_mb' in stats
        assert isinstance(stats['size'], int)
