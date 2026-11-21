import threading
import time
from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from main.lib import lookups
from main.tests.lookup_support import FetchedAtOnce


class LookupsTestCase(FetchedAtOnce, SimpleTestCase):
    def test_not_ready_until_fetched_then_kept(self):
        fetch = mock.Mock(return_value=3847)
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (False, None))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        fetch.assert_called_once_with()
        self.assertIsNone(cache.get('fetching:elevation:a'))      # the mark goes with the fetch

    def test_an_answer_of_none_is_kept_too(self):
        fetch = mock.Mock(return_value=None)
        lookups.answer('elevation:b', fetch, 60, 10)
        self.assertEqual(lookups.answer('elevation:b', fetch, 60, 10), (True, None))
        fetch.assert_called_once_with()

    def test_one_fetch_at_a_time_for_a_key(self):
        cache.set('fetching:elevation:c', True, 30)
        fetch = mock.Mock(return_value=1)
        self.assertEqual(lookups.answer('elevation:c', fetch, 60, 10), (False, None))
        fetch.assert_not_called()

    def test_no_answer_is_kept_briefly_and_logged_as_information(self):
        for problem in (requests.Timeout('slow'), requests.ConnectionError('down'), KeyError('value'), ValueError('json')):
            cache.clear()
            fetch = mock.Mock(side_effect=problem)
            with self.assertLogs('main.lib.lookups', 'INFO') as logged, \
                    mock.patch.object(cache, 'add', wraps=cache.add) as kept:
                lookups.answer('forecast:e', fetch, 3600, 600)
            self.assertEqual(logged.records[0].levelname, 'INFO', problem)
            self.assertEqual(kept.call_args.args[1:], ({'value': None}, 600), problem)
            self.assertEqual(lookups.answer('forecast:e', fetch, 3600, 600), (True, None), problem)
            fetch.assert_called_once_with()

    def test_an_unexpected_error_is_logged_as_an_error(self):
        with self.assertLogs('main.lib.lookups', 'ERROR'):
            lookups.answer('forecast:f', mock.Mock(side_effect=ZeroDivisionError), 3600, 600)
        self.assertEqual(lookups.answer('forecast:f', mock.Mock(), 3600, 600), (True, None))

    def test_a_failed_fetch_never_replaces_an_answer_kept_already(self):
        for problem in (requests.Timeout, ZeroDivisionError):     # no answer, and an unexpected error
            cache.set('county:l', {'value': 'Placer'}, 60)
            with self.assertLogs('main.lib.lookups'):
                lookups.fetched('county:l', mock.Mock(side_effect=problem), 60, 10)
            self.assertEqual(cache.get('county:l'), {'value': 'Placer'}, problem)


class LookupsInTheBackgroundTestCase(SimpleTestCase):
    def setUp(self):
        cache.clear()

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

    def test_four_fetches_run_at_once_and_more_wait_their_turn(self):
        answering, lock, running = threading.Event(), threading.Lock(), []
        self.addCleanup(answering.set)
        all_running = threading.Event()

        def fetch():
            with lock:
                running.append(1)
                if len(running) == lookups.AT_ONCE:
                    all_running.set()
            answering.wait(5)
            return 3847

        for n in range(lookups.AT_ONCE + 1):
            lookups.answer('elevation:at-once-{}'.format(n), fetch, 60, 10)
        self.assertEqual(lookups.AT_ONCE, 4)
        self.assertTrue(all_running.wait(2))
        time.sleep(0.1)
        self.assertEqual(len(running), lookups.AT_ONCE)     # the fifth waits its turn
        answering.set()
        for _ in range(50):
            if lookups.answer('elevation:at-once-4', fetch, 60, 10)[0]:
                break
            time.sleep(0.05)
        self.assertEqual(lookups.answer('elevation:at-once-4', fetch, 60, 10), (True, 3847))
