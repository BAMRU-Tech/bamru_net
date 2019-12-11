import time
import unittest

from django.conf import settings
from django.test import Client, TestCase

from main.lib import groups
from main.models import Configuration

USER = 'net_test@bamru.org'
GROUP = 'test_do@bamru.org'
ADDRESS = 'test@example.com'
SLEEP = 0.1

class GroupTestCase(TestCase):
    def setUp(self):
        Configuration.set_host_key('google_user', USER)
        Configuration.set_host_key('do_group', GROUP)
        self.group = groups.get_do_group()

    @unittest.skipUnless(settings.GOOGLE_TOKEN_FILE, 'missing config')
    def test_group(self):
        self.assertTrue(type(self.group) is groups.GoogleGroup)
        self.assertEquals(self.group.name, GROUP)

    @unittest.skipUnless(settings.GOOGLE_TOKEN_FILE, 'missing config')
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
