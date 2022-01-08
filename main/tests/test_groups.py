from dynamic_preferences.registries import global_preferences_registry
import time
import unittest

from django.conf import settings
from django.test import Client, TestCase

from dynamic_preferences.registries import global_preferences_registry
from pathlib import Path

from main.lib import groups

USER = 'net_test@bamru.net'
GROUP = 'test_do@bamru.net'
ADDRESS = 'test@example.com'
SLEEP = 0.3

class GroupTestCase(TestCase):
    def setUp(self):
        self.global_preferences = global_preferences_registry.manager()
        self.global_preferences['google__credentials'] = Path(
            settings.GOOGLE_CREDENTIALS_FILE).read_text()
        self.global_preferences['google__user'] = USER
        self.global_preferences['google__do_group'] = GROUP
        self.group = groups.get_do_group()

    @unittest.skipUnless(settings.GOOGLE_CREDENTIALS_FILE, 'missing config')
    def test_group(self):
        self.assertTrue(type(self.group) is groups.GoogleGroup)
        self.assertEquals(self.group.name, GROUP)

    @unittest.skipUnless(settings.GOOGLE_CREDENTIALS_FILE, 'missing config')
    def test_add_remove(self):
        address = ADDRESS
        # Ensure setup in consistent state
        self.group.insert(ADDRESS)
        time.sleep(SLEEP)
        self.group.delete(ADDRESS)
        time.sleep(SLEEP)
        # Start with address missing, then test adding and removing
        self.assertTrue(address not in self.group.list_emails())
        self.group.insert(address)
        time.sleep(SLEEP)
        self.assertTrue(address in self.group.list_emails())
        self.group.delete(address)
        time.sleep(SLEEP)
        self.assertTrue(address not in self.group.list_emails())
