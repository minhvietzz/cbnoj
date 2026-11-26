import logging
import os

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('judge.mcp')
_configured = False


def configure_logging():
    """Send ``judge.mcp`` log lines to MCP_LOG_FILE once; stay silent if the file is not writable."""
    global _configured
    if _configured:
        return
    _configured = True
    path = getattr(settings, 'MCP_LOG_FILE', None)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.FileHandler(path, encoding='utf-8')
    except OSError:
        return
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_call(user, tool, size, outcome):
    """Audit line. Never log arguments or tokens, only who/what/how big/result."""
    configure_logging()
    logger.info('user=%s tool=%s bytes=%d result=%s', user.username, tool, size, outcome)


def rate_limited(key, limit, window=60):
    """Fixed-window counter in the cache. Returns True when `key` has exceeded `limit` calls in `window` seconds."""
    cache_key = 'mcp:rl:%s' % key
    if cache.add(cache_key, 1, window):
        return False
    try:
        return cache.incr(cache_key) > limit
    except ValueError:
        cache.add(cache_key, 1, window)
        return False


def log_event(message, *args):
    """Free-form diagnostic line (registration problems...). Never pass tokens, secrets or user content."""
    configure_logging()
    logger.info(message, *args)
