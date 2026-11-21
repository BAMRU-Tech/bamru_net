"""Answers from outside services for the event page, such as USGS's elevation and the weather service's
forecast. No request waits on one: a request gets the answer kept for it, or, with none kept, starts it
being fetched in the background and says it isn't ready, so the page asks again. Kept in the 'lookups'
cache, which the server's processes share, apart from the rest of the site's."""
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.core.cache import caches
from django.utils.connection import ConnectionProxy

SECONDS = 10            # how long the page keeps asking for an answer before it shows nothing
# Seconds an outside service has to connect, and then to send each part of its answer. A short connect
# leaves time, within the page's SECONDS, to ask a second service when the first doesn't answer.
TIMEOUT = (4, 10)
MARKED = 30             # seconds the 'fetching' mark holds off a second fetch of the same key
AT_ONCE = 4             # fetches running at once in one server process; more wait their turn

# What a fetch raises when its service gives no answer, or one in a shape the fetch can't read.
NO_ANSWER = (requests.RequestException, ValueError, KeyError, TypeError, AttributeError)

logger = logging.getLogger(__name__)
cache = ConnectionProxy(caches, 'lookups')      # as Django's own `cache` is the 'default' one
pool = ThreadPoolExecutor(AT_ONCE, thread_name_prefix='lookup')


def answer(key, fetch, kept_for, retry_after):
    """(True, value) when an answer is kept for `key`; otherwise (False, None), and fetch() is started in the
    background unless it is running already. What fetch() returns is kept for kept_for seconds; when it
    fails, None is kept for retry_after seconds, so the service isn't asked again at once."""
    found = cache.get(key)
    if found is not None:
        return True, found['value']
    if cache.add('fetching:' + key, True, MARKED):
        pool.submit(fetched, key, fetch, kept_for, retry_after)
    return False, None


def fetched(key, fetch, kept_for, retry_after):
    """Fetch and keep the answer; on a failure, keep None, but never in place of an answer kept already
    (another fetch of the same key may have succeeded)."""
    try:
        cache.set(key, {'value': fetch()}, kept_for)
    except NO_ANSWER as problem:
        # The page shows nothing, and an outage isn't an error.
        logger.info('No answer for %s: %s', key, problem)
        cache.add(key, {'value': None}, retry_after)
    except Exception:
        logger.exception('Fetching %s failed', key)
        cache.add(key, {'value': None}, retry_after)
    finally:
        cache.delete('fetching:' + key)
