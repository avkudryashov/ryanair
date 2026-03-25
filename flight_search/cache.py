"""SWR (Stale-While-Revalidate) кэш: L1 in-memory + L2 diskcache/SQLite."""
import time
from typing import Any, Tuple

import diskcache
from cachetools import TTLCache


# TTL конфигурация (fresh_seconds, stale_seconds)
# fresh: данные считаются свежими, API не трогаем
# stale: данные устарели но пригодны — отдаём мгновенно + обновляем в фоне
TTL_AIRPORTS = (86400, 604800)       # 24ч fresh, 7 дней stale
TTL_DESTINATIONS = (1800, 21600)     # 30 мин fresh, 6ч stale
TTL_FLIGHTS = (300, 3600)            # 5 мин fresh, 1ч stale


class SWRCache:
    """Two-tier cache: L1 (in-memory TTLCache) + L2 (diskcache/SQLite) с SWR."""

    def __init__(self, cache_dir: str = ".cache_data", l1_maxsize: int = 4096,
                 l1_ttl: int = 300, size_limit: int = 256 * 1024 * 1024):
        # L2: Persistent SQLite кэш (переживает рестарт)
        self._disk = diskcache.Cache(cache_dir, size_limit=size_limit)
        # L1: In-memory TTL cache (микросекунды vs SQLite миллисекунды)
        self._l1 = TTLCache(maxsize=l1_maxsize, ttl=l1_ttl)

    def key(self, *parts) -> str:
        return "|".join(str(p) for p in parts)

    def get(self, key: str, fresh_ttl: int, stale_ttl: int) -> Tuple[Any, bool]:
        """
        L1 (in-memory) → L2 (diskcache/SQLite) с Stale-While-Revalidate.
        Returns: (data, is_stale)
        """
        # L1: in-memory (только fresh данные)
        l1_val = self._l1.get(key)
        if l1_val is not None:
            return l1_val, False

        # L2: diskcache (SQLite)
        raw = self._disk.get(key)
        if raw is None:
            return None, False
        data, timestamp = raw
        age = time.time() - timestamp
        if age < fresh_ttl:
            self._l1[key] = data  # promote to L1
            return data, False  # свежие
        elif age < stale_ttl:
            return data, True   # stale — отдаём, но нужно обновить
        else:
            return None, False  # полностью протухли

    def set(self, key: str, data: Any, stale_ttl: int):
        """Сохраняет в L1 + L2."""
        now = time.time()
        self._l1[key] = data  # L1
        self._disk.set(key, (data, now), expire=stale_ttl)  # L2

    def stats(self) -> dict:
        """Статистика кэша для отладки."""
        return {
            'size': len(self._disk),
            'volume_mb': round(self._disk.volume() / 1024 / 1024, 1),
        }

    def close(self):
        self._disk.close()

    @property
    def disk(self) -> diskcache.Cache:
        """Прямой доступ к L2 для тестов."""
        return self._disk

    @disk.setter
    def disk(self, value: diskcache.Cache):
        self._disk = value

    @property
    def l1(self) -> TTLCache:
        return self._l1
