import threading
import time
from unittest import mock

import requests
from django.core.cache import caches
from django.test import SimpleTestCase

from main.lib import lookups
from main.tests.lookup_support import FetchedAtOnce, in_memory


def free_places():
    """How many fetches could start now in this process."""
    taken = 0
    while lookups.running.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        lookups.running.release()
    return taken


@in_memory
class LookupsTestCase(FetchedAtOnce, SimpleTestCase):
    def test_not_ready_until_fetched_then_kept(self):
        fetch = mock.Mock(return_value=3847)
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (False, None))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        self.assertEqual(lookups.answer('elevation:a', fetch, 60, 10), (True, 3847))
        fetch.assert_called_once_with()
        self.assertIsNone(caches['lookups'].get('fetching:elevation:a'))      # the mark goes with the fetch
        self.assertEqual(free_places(), lookups.AT_ONCE)

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
        self.assertEqual(free_places(), lookups.AT_ONCE)

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
                    mock.patch.object(caches['lookups'], 'add', wraps=caches['lookups'].add) as kept:
                lookups.answer('forecast:e', fetch, 3600, 600)
            self.assertEqual(logged.records[0].levelname, 'INFO', problem)
            self.assertEqual(kept.call_args.args[1:], ({'value': None}, 600), problem)
            self.assertEqual(lookups.answer('forecast:e', fetch, 3600, 600), (True, None), problem)
            fetch.assert_called_once_with()

    def test_an_unexpected_error_is_logged_as_an_error(self):
        with self.assertLogs('main.lib.lookups', 'ERROR'):
            lookups.answer('forecast:f', mock.Mock(side_effect=ZeroDivisionError), 3600, 600)
        self.assertEqual(lookups.answer('forecast:f', mock.Mock(), 3600, 600), (True, None))

    def test_a_cache_it_cannot_write_gives_the_place_back(self):
        with mock.patch.object(caches['lookups'], 'add', side_effect=OSError('No space left on device')):
            with self.assertRaises(OSError):
                lookups.answer('elevation:j', mock.Mock(), 60, 10)
        self.assertEqual(free_places(), lookups.AT_ONCE)

    def test_a_thread_it_cannot_start_gives_the_place_back_and_its_mark(self):
        with mock.patch.object(lookups, 'start', side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(RuntimeError):
                lookups.answer('elevation:k', mock.Mock(), 60, 10)
        self.assertEqual(free_places(), lookups.AT_ONCE)
        self.assertIsNone(caches['lookups'].get('fetching:elevation:k'))

    def test_a_failed_fetch_never_replaces_an_answer_kept_already(self):
        caches['lookups'].set('county:l', {'value': 'Placer'}, 60)
        self.assertTrue(lookups.running.acquire(timeout=2))     # a slot, as answer() takes one
        lookups.fetched('county:l', mock.Mock(side_effect=requests.Timeout), 60, 10)
        self.assertEqual(caches['lookups'].get('county:l'), {'value': 'Placer'})
        self.assertEqual(free_places(), lookups.AT_ONCE)

    def test_a_cache_failure_in_the_fetch_is_logged_and_gives_the_place_back(self):
        self.assertTrue(lookups.running.acquire(timeout=2))     # a slot, as answer() takes one
        with mock.patch.object(caches['lookups'], 'set', side_effect=OSError('No space left on device')), \
                self.assertLogs('main.lib.lookups', 'ERROR'):
            lookups.fetched('county:m', mock.Mock(return_value='Placer'), 60, 10)
        self.assertEqual(free_places(), lookups.AT_ONCE)

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
