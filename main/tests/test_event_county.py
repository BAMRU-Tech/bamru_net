import threading
import time
from datetime import timedelta
from unittest import mock

import requests
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.dynamic_preferences_registry import EventCountyBorderMiles
from main.lib import county
from main.lib.county import RETRY_AFTER, county_text, text_for
from main.models import Event, Member
from main.lib.lookups import cache
from main.tests.lookup_support import FetchedAtOnce, in_memory

# Public places only. The tests never call USGS or the Census Bureau: each answer is mocked, as the
# services answered for these points on 20 Nov 2026, with the field names each sends.
DONNER_SUMMIT = (39.3157, -120.3277)
USGS = 'https://carto.nationalmap.gov/arcgis/rest/services/govunits/MapServer/23/query'
CENSUS = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/82/query'
# The fields each service's replies hold the county's name and state FIPS code in: USGS's are in lower case.
FIELDS = {USGS: ('county_name', 'state_fipscode'), CENSUS: ('BASENAME', 'STATE')}

# The services' counties for a point (distance 0) and within 3 miles of it, by (lat, lon).
COUNTIES = {
    (37.8817, -121.9142): ([('Contra Costa', '06')], [('Contra Costa', '06')]),                  # Mount Diablo
    DONNER_SUMMIT: ([('Placer', '06')], [('Nevada', '06'), ('Placer', '06')]),
    (38.6847, -120.0653): ([('Alpine', '06')], [('El Dorado', '06'), ('Alpine', '06'), ('Amador', '06')]),  # Kirkwood
    (39.0968, -120.0324): ([('Placer', '06')], [('Douglas', '32'), ('El Dorado', '06'), ('Carson City', '32'),
                                                ('Placer', '06')]),                                # mid Lake Tahoe
    (45.6387, -122.6615): ([('Clark', '53')], [('Multnomah', '41'), ('Clark', '53')]),           # Vancouver, WA
    (32.5149, -117.0382): ([], [('San Diego', '06')]),                                           # Tijuana
}


def services_answer(failing=(), refusing=()):
    """requests.get as the services answer: Census's and USGS's fields, a failure for a URL in `failing`,
    and an ArcGIS error reply for one in `refusing`."""
    def get(url, params, timeout):
        if url in failing:
            raise requests.ConnectionError('down')
        response = mock.Mock()
        if url in refusing:
            response.json.return_value = {'error': {'code': 500, 'message': 'Unable to complete operation.'}}
            return response
        lon, lat = (float(degrees) for degrees in params['geometry'].split(','))
        inside, near = COUNTIES[(lat, lon)]
        name_field, state_field = FIELDS[url]
        response.json.return_value = {'features': [{'attributes': {name_field: name, state_field: state}}
                                                   for name, state in (near if 'distance' in params else inside)]}
        return response
    return mock.patch.object(county.requests, 'get', mock.Mock(side_effect=get))


def set_border_miles(test, miles):
    preferences = global_preferences_registry.manager()
    usual = preferences['general__event_county_border_miles']
    preferences['general__event_county_border_miles'] = miles
    # Preferences are cached outside the test's database transaction, so put it back.
    test.addCleanup(preferences.__setitem__, 'general__event_county_border_miles', usual)


def county_for(lat, lon):
    """The county line once fetched: the first ask starts the fetch and isn't ready, the second has it."""
    assert county_text(lat, lon) == (False, None)
    ready, text = county_text(lat, lon)
    assert ready
    return text


@in_memory
class CountyTextTestCase(FetchedAtOnce, TestCase):

    def test_a_point_well_inside_a_county(self):
        with services_answer():
            self.assertEqual(county_for(37.8817, -121.9142), 'Contra Costa')

    def test_near_a_county_line_the_one_it_is_in_comes_first(self):
        with services_answer():
            self.assertEqual(county_for(*DONNER_SUMMIT), 'Placer, bordering Nevada')
            self.assertEqual(county_for(38.6847, -120.0653), 'Alpine, bordering Amador and El Dorado')

    def test_counties_in_another_state_have_their_state(self):
        with services_answer():
            self.assertEqual(county_for(39.0968, -120.0324),
                             'Placer, bordering El Dorado, Carson City (NV) and Douglas (NV)')
            self.assertEqual(county_for(45.6387, -122.6615), 'Clark, bordering Multnomah (OR)')

    def test_a_point_in_no_county_has_none(self):
        with services_answer():
            self.assertIsNone(county_for(32.5149, -117.0382))

    def test_asks_usgs_for_the_county_and_those_within_the_setting(self):
        with services_answer() as get:
            county_for(*DONNER_SUMMIT)
        inside, near = sorted(get.call_args_list, key=lambda call: 'distance' in call.kwargs['params'])
        self.assertEqual((inside.args[0], near.args[0]), (USGS, USGS))
        self.assertEqual(inside.kwargs['params'], {
            'geometry': '-120.3277,39.3157', 'geometryType': 'esriGeometryPoint', 'inSR': 4326,
            'spatialRel': 'esriSpatialRelIntersects', 'outFields': 'county_name,state_fipscode',
            'returnGeometry': 'false', 'f': 'json'})
        self.assertEqual(near.kwargs['params'], dict(inside.kwargs['params'], distance=3.0, units='esriSRUnit_StatuteMile'))

    def test_the_border_distance_comes_from_the_site_setting(self):
        set_border_miles(self, 0)
        with services_answer() as get:
            self.assertEqual(county_for(*DONNER_SUMMIT), 'Placer')
        self.assertEqual(['distance' in call.kwargs['params'] for call in get.call_args_list], [False])

    def test_the_census_bureau_when_usgs_gives_no_answer(self):
        for problem in ({'failing': (USGS,)}, {'refusing': (USGS,)}):
            cache.clear()
            with services_answer(**problem) as get, self.assertLogs('main.lib.county', 'INFO'):
                self.assertEqual(county_for(*DONNER_SUMMIT), 'Placer, bordering Nevada', problem)
            # Once one of USGS's two questions fails, the other may be dropped before it is asked.
            asked = [call.args[0] for call in get.call_args_list]
            self.assertIn(asked.count(USGS), (1, 2), problem)
            self.assertEqual(asked.count(CENSUS), 2, problem)

    def test_the_census_bureau_without_waiting_for_usgs_s_other_question(self):
        # USGS hangs on one question and, once that one is under way, refuses the other: the Census Bureau
        # is asked at once, whichever of the two hangs.
        answers = services_answer().new.side_effect
        for near_hangs in (True, False):
            cache.clear()
            hanging, hanging_asked = threading.Event(), threading.Event()
            self.addCleanup(hanging.set)

            def get(url, params, timeout):
                if url == USGS:
                    if ('distance' in params) == near_hangs:
                        hanging_asked.set()
                        hanging.wait(10)
                    else:
                        hanging_asked.wait(5)
                    raise requests.ConnectionError('refused')
                return answers(url, params, timeout)
            started = time.monotonic()
            with mock.patch.object(county.requests, 'get', mock.Mock(side_effect=get)), \
                    self.assertLogs('main.lib.county', 'INFO'):
                self.assertEqual(county_for(*DONNER_SUMMIT), 'Placer, bordering Nevada', near_hangs)
            self.assertLess(time.monotonic() - started, 2, near_hangs)

    def test_neither_answering_gives_none_kept_briefly(self):
        with services_answer(failing=(USGS, CENSUS)), self.assertLogs('main.lib.lookups', 'INFO'), \
                mock.patch.object(cache, 'add', wraps=cache.add) as kept:
            self.assertIsNone(county_for(*DONNER_SUMMIT))
        self.assertEqual(kept.call_args.args[1:], ({'value': None}, RETRY_AFTER))

    def test_the_text_names_each_county_once(self):
        self.assertEqual(text_for([('Placer', 'CA'), ('Nevada', 'CA')], [('Nevada', 'CA'), ('Placer', 'CA')]),
                         'Placer, bordering Nevada')
        self.assertEqual(text_for([('Placer', 'CA')], [('Placer', 'CA')]), 'Placer')
        self.assertIsNone(text_for([], [('San Diego', 'CA')]))

    def test_the_border_distance_is_not_negative(self):
        self.assertEqual(EventCountyBorderMiles.default, 3.0)
        with self.assertRaises(ValidationError):
            EventCountyBorderMiles().validate(-1)


@in_memory
class EventPageCountyTestCase(FetchedAtOnce, TestCase):

    def setUp(self):
        super().setUp()
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8),
            lat=str(DONNER_SUMMIT[0]), lon=str(DONNER_SUMMIT[1]))
        self.url = '/event/{}/county/'.format(self.event.id)
        self.client.force_login(Member.objects.create(username='jane roe', status='T'))

    def test_the_county_line_once_fetched(self):
        with services_answer():
            self.assertEqual(self.client.get(self.url).json(), {'ready': False, 'county': None})
            self.assertEqual(self.client.get(self.url).json(), {'ready': True, 'county': 'Placer, bordering Nevada'})

    def test_the_county_needs_a_signed_in_member(self):
        self.client.logout()
        with services_answer() as get:
            self.assertEqual(self.client.get(self.url).status_code, 302)
        get.assert_not_called()

    def test_no_county_without_a_whole_point(self):
        for lat, lon in ((None, None), ('39.3157', None), ('39.3157', 'west')):
            self.event.lat, self.event.lon = lat, lon
            self.event.save()
            with services_answer() as get:
                self.assertEqual(self.client.get(self.url).json(), {'ready': True, 'county': None}, (lat, lon))
            get.assert_not_called()

    def test_the_event_page_asks_for_the_county_first_under_the_section(self):
        response = self.client.get('/event/{}/'.format(self.event.id))
        self.assertContains(response, '<div class="location-details-body">\n'
                                      '      <div id="event-county-line" hidden><strong>County:</strong> '
                                      '<span id="event-county"></span></div>')
        self.assertContains(response, "whenReady('{}'".format(self.url))
        self.event.lat = self.event.lon = None
        self.event.save()
        response = self.client.get('/event/{}/'.format(self.event.id))
        self.assertNotContains(response, 'County:')
        self.assertNotContains(response, self.url)
