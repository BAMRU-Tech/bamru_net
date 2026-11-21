"""For tests of the event page's outside lookups (main.lib.lookups): the cache emptied before each test,
and each fetch run during the ask that starts it rather than in the background, so the next ask has its
answer."""
from unittest import mock

from django.core.cache import cache

from main.lib import lookups


class FetchedAtOnce:
    def setUp(self):
        super().setUp()
        cache.clear()
        patched = mock.patch.object(lookups.pool, 'submit', lambda target, *args: target(*args))
        patched.start()
        self.addCleanup(patched.stop)
