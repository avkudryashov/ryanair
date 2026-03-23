"""Тесты кэширования: diskcache, SWR, persistence."""
import time
import diskcache
import pytest


class TestCacheGetSet:
    """Базовые операции кэша."""

    def test_cache_set_and_get_fresh(self, searcher):
        key = "test:fresh"
        searcher._cache_set(key, {"data": 42}, stale_ttl=3600)

        data, is_stale = searcher._cache_get(key, fresh_ttl=60, stale_ttl=3600)
        assert data == {"data": 42}
        assert is_stale is False

    def test_cache_miss_returns_none(self, searcher):
        data, is_stale = searcher._cache_get("nonexistent", 60, 3600)
        assert data is None
        assert is_stale is False

    def test_cache_stale_after_fresh_ttl(self, searcher):
        key = "test:stale"
        searcher._cache_set(key, "value", stale_ttl=3600)
        # Подменяем timestamp чтобы данные стали stale
        raw_data, ts = searcher._cache.get(key)
        searcher._cache.set(key, (raw_data, time.time() - 120), expire=3600)

        data, is_stale = searcher._cache_get(key, fresh_ttl=60, stale_ttl=3600)
        assert data == "value"
        assert is_stale is True

    def test_cache_expired_after_stale_ttl(self, searcher):
        key = "test:expired"
        searcher._cache_set(key, "value", stale_ttl=3600)
        raw_data, ts = searcher._cache.get(key)
        searcher._cache.set(key, (raw_data, time.time() - 7200), expire=3600)

        data, is_stale = searcher._cache_get(key, fresh_ttl=60, stale_ttl=3600)
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
        k1 = searcher._cache_key("flights", "VLC", "BGY", "2026-05-01", 2)
        k2 = searcher._cache_key("flights", "VLC", "BGY", "2026-05-01", 2)
        assert k1 == k2

    def test_cache_key_different_params(self, searcher):
        k1 = searcher._cache_key("flights", "VLC", "BGY", "2026-05-01", 2)
        k2 = searcher._cache_key("flights", "VLC", "MXP", "2026-05-01", 2)
        assert k1 != k2


class TestCacheStats:
    def test_cache_stats(self, searcher):
        stats = searcher.cache_stats()
        assert 'size' in stats
        assert 'volume_mb' in stats
        assert isinstance(stats['size'], int)
