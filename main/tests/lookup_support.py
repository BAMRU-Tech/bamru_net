"""For tests of the event page's outside lookups (main.lib.lookups): their cache in memory, apart from
the files the servers share, and each fetch run during the ask that starts it rather than in the
background, so the next ask has its answer."""
from unittest import mock

from django.core.cache import caches
from django.test import override_settings

from main.lib import lookups

in_memory = override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'lookups': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'lookups-under-test'},
})


class FetchedAtOnce:
    def setUp(self):
        super().setUp()
        caches['lookups'].clear()
        patched = mock.patch.object(lookups, 'start', lambda target, *args: target(*args))
        patched.start()
        self.addCleanup(patched.stop)
