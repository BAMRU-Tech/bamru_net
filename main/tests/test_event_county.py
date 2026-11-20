from collections import Counter
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.dynamic_preferences_registry import EventCountyBorderMiles
from main.lib.county import counties, county_text
from main.models import Event, Member

# Public places only.
MOUNT_DIABLO = (37.8817, -121.9142)
DONNER_SUMMIT = (39.3157, -120.3277)
KIRKWOOD = (38.6847, -120.0653)
MID_LAKE_TAHOE = (39.0968, -120.0324)
OFF_POINT_REYES = (37.99, -123.30)
GRAND_CANYON = (36.0544, -112.1401)


def set_border_miles(test, miles):
    preferences = global_preferences_registry.manager()
    usual = preferences['general__event_county_border_miles']
    preferences['general__event_county_border_miles'] = miles
    # Preferences are cached outside the test's database transaction, so put it back.
    test.addCleanup(preferences.__setitem__, 'general__event_county_border_miles', usual)


class CountyTextTestCase(TestCase):

    def test_the_file_has_every_county_of_the_three_states(self):
        self.assertEqual(Counter(state for _, state, _, _ in counties()), {'CA': 58, 'OR': 36, 'NV': 17})

    def test_a_point_well_inside_a_county(self):
        self.assertEqual(county_text(*MOUNT_DIABLO), 'Contra Costa')

    def test_a_point_near_a_county_line_names_both_counties(self):
        self.assertEqual(county_text(*DONNER_SUMMIT), 'Border of Placer and Nevada')

    def test_three_counties(self):
        self.assertEqual(county_text(*KIRKWOOD), 'Border of Alpine, Amador and El Dorado')

    def test_counties_across_a_state_line_are_grouped_by_state(self):
        self.assertEqual(county_text(*MID_LAKE_TAHOE), 'Border of Placer and El Dorado, CA, and Douglas and Carson City, NV')

    def test_a_point_in_no_county_has_none(self):
        for point in (OFF_POINT_REYES, GRAND_CANYON):
            self.assertIsNone(county_text(*point), msg=point)

    def test_the_border_distance_comes_from_the_site_setting(self):
        set_border_miles(self, 0)
        self.assertEqual(county_text(*DONNER_SUMMIT), 'Placer')

    def test_the_border_distance_is_not_negative(self):
        self.assertEqual(EventCountyBorderMiles.default, 3.0)
        with self.assertRaises(ValidationError):
            EventCountyBorderMiles().validate(-1)


class EventPageCountyTestCase(TestCase):

    def setUp(self):
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))
        self.client.force_login(Member.objects.create(username='jane roe', status='T'))

    def page(self):
        return self.client.get('/event/{}/'.format(self.event.id))

    def test_the_event_page_names_the_county_first_under_location(self):
        self.event.lat, self.event.lon = (str(degrees) for degrees in DONNER_SUMMIT)
        self.event.save()
        self.assertContains(self.page(), '<div class="location-details-body">\n'
                                         '      <div><strong>County:</strong> Border of Placer and Nevada</div>')

    def test_no_county_line_without_a_point_in_a_county(self):
        for lat, lon in ((None, None), ('39.3157', None), ('39.3157', 'west'), (str(GRAND_CANYON[0]), str(GRAND_CANYON[1]))):
            self.event.lat, self.event.lon = lat, lon
            self.event.save()
            self.assertNotContains(self.page(), 'County:', msg_prefix='{}, {}'.format(lat, lon))
