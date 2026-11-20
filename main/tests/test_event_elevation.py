from datetime import timedelta
from unittest import mock

import requests
from django.core.cache import caches
from django.test import TestCase
from django.utils import timezone

from main.lib import elevation, lookups
from main.lib.elevation import RETRY_AFTER, altitude_band, elevation_feet
from main.tests.lookup_support import FetchedAtOnce, in_memory
from main.models import Event, Member

# Public places only. The tests never call USGS: each answer is mocked.
MOUNT_DIABLO = (37.8817, -121.9142)


def usgs_answers(value=None, problem=None):
    """requests.get as USGS would answer: `value`, or `problem` raised (an HTTP error by raise_for_status)."""
    response = mock.Mock()
    response.json.return_value = {'value': value}
    if isinstance(problem, requests.HTTPError):
        response.raise_for_status.side_effect, problem = problem, None
    return mock.patch.object(elevation.requests, 'get', mock.Mock(return_value=response, side_effect=problem))


@in_memory
class ElevationTestCase(FetchedAtOnce, TestCase):
    def test_altitude_bands_from_the_cdc_risk_categories(self):
        for feet, band in ((14505, 'danger'), (11150, 'danger'), (11149, 'extreme-caution'), (9000, 'extreme-caution'),
                           (8999, 'caution'), (8000, 'caution'), (7999, None), (-280, None), (None, None)):
            self.assertEqual(altitude_band(feet)[0], band, feet)

    def test_whole_feet_asked_once_per_point_in_the_background(self):
        with usgs_answers(3847.4941) as get:
            self.assertEqual(elevation_feet(*MOUNT_DIABLO), (False, None))
            self.assertEqual(elevation_feet(*MOUNT_DIABLO), (True, 3847))
            self.assertEqual(elevation_feet(*MOUNT_DIABLO), (True, 3847))
        get.assert_called_once_with(elevation.SERVICE, timeout=lookups.TIMEOUT, params={
            'x': -121.9142, 'y': 37.8817, 'wkid': 4326, 'units': 'Feet', 'includeDate': 'false'})

    def test_nothing_outside_the_us_or_off_land(self):
        for value in (-1000000, 0):
            caches['lookups'].clear()
            with usgs_answers(value):
                elevation_feet(*MOUNT_DIABLO)
                self.assertEqual(elevation_feet(*MOUNT_DIABLO), (True, None), value)

    def test_a_point_below_sea_level_keeps_its_depth(self):
        with usgs_answers(-279.6):                  # Badwater Basin, Death Valley
            elevation_feet(36.2299, -116.7672)
            self.assertEqual(elevation_feet(36.2299, -116.7672), (True, -280))

    def test_no_answer_is_kept_only_briefly(self):
        for problem in (requests.Timeout('slow'), requests.HTTPError('503'), requests.ConnectionError('down')):
            caches['lookups'].clear()
            with usgs_answers(problem=problem) as get, \
                    mock.patch.object(caches['lookups'], 'set', wraps=caches['lookups'].set) as kept:
                elevation_feet(*MOUNT_DIABLO)
                self.assertEqual(elevation_feet(*MOUNT_DIABLO), (True, None), problem)
            get.assert_called_once()
            self.assertEqual(kept.call_args.args[2], RETRY_AFTER)


@in_memory
class EventElevationPageTestCase(FetchedAtOnce, TestCase):
    def setUp(self):
        super().setUp()
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(type='training', title='Night navigation', location='Mount Diablo',
                                          start_at=start, finish_at=start + timedelta(hours=8),
                                          lat=str(MOUNT_DIABLO[0]), lon=str(MOUNT_DIABLO[1]))
        self.url = '/event/{}/elevation/'.format(self.event.id)

    def sign_in(self):
        self.client.force_login(Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T'))

    def test_the_elevation_needs_a_signed_in_member(self):
        with usgs_answers(3847.49) as get:
            self.assertEqual(self.client.get(self.url).status_code, 302)
        get.assert_not_called()

    def test_the_elevation_of_the_events_point_once_fetched(self):
        self.sign_in()
        with usgs_answers(3847.49):
            self.assertEqual(self.client.get(self.url).json(), {'ready': False, 'feet': None, 'band': None, 'note': None})
            self.assertEqual(self.client.get(self.url).json(), {'ready': True, 'feet': 3847, 'band': None, 'note': None})

    def test_a_high_point_is_shaded_by_its_risk_of_altitude_sickness(self):
        self.sign_in()
        with usgs_answers(14505.2):                 # Mount Whitney's summit
            self.client.get(self.url)
            self.assertEqual(self.client.get(self.url).json(), {
                'ready': True, 'feet': 14505, 'band': 'danger',
                'note': 'High risk of altitude sickness sleeping here the first night, '
                        'higher still working hard soon after arriving'})

    def test_no_elevation_without_a_whole_point(self):
        self.sign_in()
        for lat, lon in ((None, None), ('37.8817', None), ('north', '-121.9142')):
            self.event.lat, self.event.lon = lat, lon
            self.event.save()
            with usgs_answers(3847.49) as get:
                self.assertEqual(self.client.get(self.url).json(),
                                 {'ready': True, 'feet': None, 'band': None, 'note': None}, (lat, lon))
            get.assert_not_called()

    def test_event_page_asks_for_the_elevation_only_with_a_point(self):
        self.sign_in()
        page = '/event/{}/'.format(self.event.id)
        response = self.client.get(page)
        self.assertContains(response, '<div id="event-elevation-line" hidden><strong>Elevation:</strong>\n'
                                      '      <span id="event-elevation" title="Elevation at the point, from USGS"></span></div>')
        page_text = response.content.decode()
        self.assertLess(page_text.index('<strong>County:</strong>'), page_text.index('<strong>Elevation:</strong>'))
        self.assertLess(page_text.index('<strong>Elevation:</strong>'), page_text.index('Daylight:</strong>'))
        self.assertLess(page_text.index('Daylight:</strong>'), page_text.index('<strong>Weather:</strong>'))
        self.assertContains(response, "whenReady('{}'".format(self.url))
        self.assertContains(response, 'var until = Date.now() + 10 * 1000;')
        self.event.lat = self.event.lon = None
        self.event.save()
        response = self.client.get(page)
        self.assertNotContains(response, 'event-elevation')
        self.assertNotContains(response, self.url)
