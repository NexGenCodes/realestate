from django.core.cache import cache

def set_key(key, value, ttl=None):
    """Set a value in the cache with an optional TTL."""
    cache.set(key, value, timeout=ttl)

def get_key(key):
    """Get a value from the cache."""
    return cache.get(key)

def delete_key(key):
    """Delete a value from the cache."""
    cache.delete(key)

def get_ttl(key):
    """Get the remaining TTL for a key."""
    return cache.ttl(key)
