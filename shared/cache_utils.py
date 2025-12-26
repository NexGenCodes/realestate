import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)


def set_key(key, value, ttl=None):
    """Set a value in the cache with an optional TTL."""
    try:
        cache.set(key, value, timeout=ttl)
        logger.debug(f"Cache SET: key={key} (ttl={ttl})")
    except Exception as e:
        logger.error(f"Cache SET FAILED: key={key}, error={str(e)}")


def get_key(key):
    """Get a value from the cache."""
    try:
        value = cache.get(key)
        if value:
            logger.debug(f"Cache GET: key={key} (HIT)")
        else:
            logger.debug(f"Cache GET: key={key} (MISS)")
        return value
    except Exception as e:
        logger.error(f"Cache GET FAILED: key={key}, error={str(e)}")
        return None


def delete_key(key):
    """Delete a value from the cache."""
    try:
        cache.delete(key)
        logger.debug(f"Cache DELETE: key={key}")
    except Exception as e:
        logger.error(f"Cache DELETE FAILED: key={key}, error={str(e)}")


def get_ttl(key):
    """Get the remaining TTL for a key."""
    try:
        return cache.ttl(key)
    except Exception as e:
        logger.error(f"Cache TTL FAILED: key={key}, error={str(e)}")
        return 0
