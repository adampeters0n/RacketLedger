"""In-process cache for singleton settings so Neon can stay asleep.

Writes go through Django's cache; population is deferred with
``transaction.on_commit`` so TestCase rollbacks never leak stale objects.
"""

from django.core.cache import cache
from django.db import transaction

DEFAULT_TTL = 3600  # 1 hour; save() still invalidates immediately


def cache_key(model_cls) -> str:
    return f"core.singleton.{model_cls._meta.label_lower}"


def get_cached_singleton(model_cls):
    obj = cache.get(cache_key(model_cls))
    if isinstance(obj, model_cls):
        return obj
    return None


def set_cached_singleton(model_cls, obj, ttl: int = DEFAULT_TTL) -> None:
    key = cache_key(model_cls)

    def _store():
        cache.set(key, obj, ttl)

    transaction.on_commit(_store)


def invalidate_singleton(model_cls) -> None:
    cache.delete(cache_key(model_cls))
