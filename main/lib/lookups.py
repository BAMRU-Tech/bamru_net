"""Answers from outside services for the event page, such as USGS's elevation and the weather service's
forecast. No request waits on one: a request gets the answer kept for it, or, with none kept, starts it
being fetched in the background and says it isn't ready, so the page asks again. Kept in the 'lookups'
cache, which the server's processes share, apart from the rest of the site's."""
import logging
import threading

import requests
from django.core.cache import caches

SECONDS = 10            # how long the page keeps asking for an answer before it shows nothing
TIMEOUT = 10            # seconds an outside service has to connect, and to send each part of its answer
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
    if running.acquire(blocking=False):
        if lookups.add('fetching:' + key, True, 3 * TIMEOUT):
            start(fetched, key, fetch, kept_for, retry_after)
        else:
            running.release()
    return False, None


def start(target, *args):
    threading.Thread(target=target, args=args, daemon=True).start()


def fetched(key, fetch, kept_for, retry_after):
    lookups = caches['lookups']
    try:
        lookups.set(key, {'value': fetch()}, kept_for)
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as problem:
        # No answer, or one in a shape this can't read: the page shows nothing, and an outage isn't an error.
        logger.info('No answer for %s: %s', key, problem)
        lookups.set(key, {'value': None}, retry_after)
    except Exception:
        logger.exception('Fetching %s failed', key)
        lookups.set(key, {'value': None}, retry_after)
    finally:
        lookups.delete('fetching:' + key)
        running.release()
