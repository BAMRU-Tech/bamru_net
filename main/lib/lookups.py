"""Answers from outside services for the event page, such as USGS's elevation and the weather service's
forecast. No request waits on one: a request gets the answer kept for it, or, with none kept, starts it
being fetched in the background and says it isn't ready, so the page asks again. Kept in the 'lookups'
cache, which the server's processes share, apart from the rest of the site's."""
import logging
import threading

import requests
from django.core.cache import caches

SECONDS = 10            # how long the page keeps asking for an answer before it shows nothing
# Seconds an outside service has to connect, and then to send each part of its answer. A short connect
# leaves time, within the page's SECONDS, to ask a second service when the first doesn't answer.
TIMEOUT = (4, 10)
MARKED = 30             # seconds the 'fetching' mark holds off a second fetch of the same key
AT_ONCE = 4             # fetches running at once in one server process

logger = logging.getLogger(__name__)
running = threading.BoundedSemaphore(AT_ONCE)


def answer(key, fetch, kept_for, retry_after):
    """(True, value) when an answer is kept for `key`; otherwise (False, None), and fetch() is started in the
    background unless it is running already. What fetch() returns is kept for kept_for seconds; when it
    fails, None is kept for retry_after seconds, so the service isn't asked again at once."""
    lookups = caches['lookups']
    found = lookups.get(key)
    if found is not None:
        return True, found['value']
    if not running.acquire(blocking=False):
        return False, None
    started = False
    try:
        if lookups.add('fetching:' + key, True, MARKED):
            try:
                start(fetched, key, fetch, kept_for, retry_after)
                started = True
            finally:
                if not started:
                    lookups.delete('fetching:' + key)
    finally:
        if not started:         # the fetch, once started, gives its place back itself
            running.release()
    return False, None


def start(target, *args):
    threading.Thread(target=target, args=args, daemon=True).start()


def fetched(key, fetch, kept_for, retry_after):
    """Fetch and keep the answer; on a failure, keep None, but never in place of an answer kept already
    (another fetch of the same key may have succeeded). Always gives its place back, even when the cache
    itself fails."""
    try:
        try:
            caches['lookups'].set(key, {'value': fetch()}, kept_for)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as problem:
            # No answer, or one in a shape this can't read: the page shows nothing, and an outage isn't an error.
            logger.info('No answer for %s: %s', key, problem)
            caches['lookups'].add(key, {'value': None}, retry_after)
        except Exception:
            logger.exception('Fetching %s failed', key)
            caches['lookups'].add(key, {'value': None}, retry_after)
        finally:
            caches['lookups'].delete('fetching:' + key)
    except Exception:
        logger.exception('Keeping the answer for %s failed', key)
    finally:
        running.release()
