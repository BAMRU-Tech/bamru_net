import threading
import time
from unittest import mock

import requests
from django.core.cache import caches
from django.test import SimpleTestCase

from main.lib import lookups
from main.tests.lookup_support import FetchedAtOnce, in_memory


@in_memory
class LookupsTestCase(FetchedAtOnce, SimpleTestCase):
    def test_not_ready_until_fetched_then_kept(self):
        fetch = mock.Mock(return_value=3847)
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (False, None))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        fetch.assert_called_once_with()

    def test_an_answer_of_none_is_kept_too(self):
        fetch = mock.Mock(return_value=None)
        lookups.answer('elevation:b', fetch, 60, 10)
        self.assertEqual(lookups.answer('elevation:b', fetch, 60, 10), (True, None))
        fetch.assert_called_once_with()

    def test_one_fetch_at_a_time_for_a_key(self):
        caches['lookups'].set('fetching:elevation:c', True, 30)
        fetch = mock.Mock(return_value=1)
        self.assertEqual(lookups.answer('elevation:c', fetch, 60, 10), (False, None))
        fetch.assert_not_called()

    def test_no_more_than_at_once_fetches_in_a_process(self):
        taken = [lookups.running.acquire(blocking=False) for _ in range(lookups.AT_ONCE)]
        self.addCleanup(lambda: [lookups.running.release() for held in taken if held])
        fetch = mock.Mock(return_value=1)
        self.assertEqual(lookups.answer('elevation:d', fetch, 60, 10), (False, None))
        fetch.assert_not_called()
        self.assertIsNone(caches['lookups'].get('fetching:elevation:d'))     # free for a later ask

    def test_no_answer_is_kept_briefly_and_logged_as_information(self):
        for problem in (requests.Timeout('slow'), requests.ConnectionError('down'), KeyError('value'), ValueError('json')):
            caches['lookups'].clear()
            fetch = mock.Mock(side_effect=problem)
            with self.assertLogs('main.lib.lookups', 'INFO') as logged, \
                    mock.patch.object(caches['lookups'], 'set', wraps=caches['lookups'].set) as kept:
                lookups.answer('forecast:e', fetch, 3600, 600)
            self.assertEqual(logged.records[0].levelname, 'INFO', problem)
            self.assertEqual(kept.call_args.args[1:], ({'value': None}, 600), problem)
            self.assertEqual(lookups.answer('forecast:e', fetch, 3600, 600), (True, None), problem)
            fetch.assert_called_once_with()

    def test_an_unexpected_error_is_logged_as_an_error(self):
        with self.assertLogs('main.lib.lookups', 'ERROR'):
            lookups.answer('forecast:f', mock.Mock(side_effect=ZeroDivisionError), 3600, 600)
        self.assertEqual(lookups.answer('forecast:f', mock.Mock(), 3600, 600), (True, None))

    def test_each_fetch_frees_its_place(self):
        for key in range(lookups.AT_ONCE + 2):
            lookups.answer('elevation:g{}'.format(key), mock.Mock(side_effect=requests.Timeout), 60, 10)
        fetch = mock.Mock(return_value=5)
        lookups.answer('elevation:h', fetch, 60, 10)
        fetch.assert_called_once_with()


@in_memory
class LookupsInTheBackgroundTestCase(SimpleTestCase):
    def setUp(self):
        caches['lookups'].clear()

    def test_the_ask_returns_while_the_service_is_still_answering(self):
        answering = threading.Event()
        fetch = mock.Mock(side_effect=lambda: answering.wait(5) and 3847)
        started = time.monotonic()
        self.assertEqual(lookups.answer('elevation:i', fetch, 60, 10), (False, None))
        self.assertLess(time.monotonic() - started, 0.5)
        answering.set()
        for _ in range(50):
            ready, feet = lookups.answer('elevation:i', fetch, 60, 10)
            if ready:
                break
            time.sleep(0.05)
        self.assertEqual((ready, feet), (True, 3847))
        fetch.assert_called_once_with()
