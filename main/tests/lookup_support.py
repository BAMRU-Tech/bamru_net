"""For tests of the event page's outside lookups (main.lib.lookups): their cache in memory, apart from
the files the servers share, and emptied before each test; and each fetch run during the ask that starts
it rather than in the background, so the next ask has its answer, with no pause before a service is asked
once more (self.paused)."""
from unittest import mock

import requests
from django.test import override_settings

from main.lib import lookups
from main.lib.lookups import cache

in_memory = override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'lookups': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'lookups-under-test'},
})


class FetchedAtOnce:
    def setUp(self):
        super().setUp()
        cache.clear()
        patched = mock.patch.object(lookups.pool, 'submit', lambda target, *args: target(*args))
        patched.start()
        self.addCleanup(patched.stop)
        patched = mock.patch.object(lookups, 'time')       # lookups' own reference, not time.sleep for every thread
        self.paused = patched.start().sleep
        self.addCleanup(patched.stop)


def http_error(status, reason):
    """The error raise_for_status raises for an answer with this status."""
    return requests.HTTPError('{} {}'.format(status, reason), response=mock.Mock(status_code=status))
