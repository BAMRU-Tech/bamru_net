from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.dynamic_preferences_registry import EventArea
from main.lib.lat_lon import EXAMPLES, UNREADABLE, NotAPoint, area_edges, area_warning, read_point
from main.models import Event, Member
from main.views.event_views import EventForm

# Public places only. Donner Summit is inside the team's usual area; the Grand Canyon is outside it.
DONNER = (39.3157, -120.3277)
GRAND_CANYON = (36.0544, -112.1401)
OUTSIDE = 'This point is outside the area the team usually works in. Check its numbers and minus signs.'
# Within about 2 m. The UTM and USNG answers below come from pyproj 3.8 and the mgrs package,
# run separately, so these tests check the conversions against an independent source.
CLOSE = 2e-5
# One point in each of the five forms CalTopo's point panel lists, as UTM, USNG, DD, DDM and DMS.
# Their rounding, to a second in DMS, puts them up to half a second (15 m) apart.
CALTOPO_PANELS = (
    ((37.88167, -121.91417), ('10S 0595487E 4193242N', '10S EG 95487 93242', '37.88167, -121.91417',
                              "37°52.900', -121°54.850'", '37°52\'54", -121°54\'51"')),    # Mount Diablo
    ((40.30501, -121.04626), ('10T 0666031E 4463443N', '10T FK 66031 63443', '40.30501, -121.04626',
                              "40°18.301', -121°02.776'", '40°18\'18", -121°02\'47"')),
    ((40.42881, -124.26613), ('10T 0392601E 4476122N', '10T CK 92601 76122', '40.42881, -124.26613',
                              "40°25.729', -124°15.968'", '40°25\'44", -124°15\'58"')),
    ((39.45817, -110.97440), ('12S 0502202E 4367623N', '12S WJ 02202 67623', '39.45817, -110.97440',
                              "39°27.490', -110°58.464'", '39°27\'29", -110°58\'28"')),     # Utah: outside
)
HALF_A_SECOND = 1.5e-4


class ReadPointTestCase(TestCase):
    """Every form the Lat/Lon box reads, and what it reads each as."""

    def assertReads(self, text, lat, lon, form, delta=CLOSE):
        point = read_point(text)
        self.assertAlmostEqual(point.lat, lat, delta=delta, msg=text)
        self.assertAlmostEqual(point.lon, lon, delta=delta, msg=text)
        self.assertEqual(point.form, form, msg=text)

    def test_decimal_degrees(self):
        for text in ('39.3157, -120.3277', '39.3157 -120.3277', '39.3157,-120.3277',
                     '39.3157 N, 120.3277 W', 'N39.3157 W120.3277', '39.3157°N 120.3277°W',
                     'W120.3277 N39.3157', 'Lat: 39.3157 Long: -120.3277', 'Latitude: 39.3157 Longitude: -120.3277',
                     'lat 39.3157 lng -120.3277', '39.3157 deg N 120.3277 deg W', '39.3157, −120.3277',
                     '39.3157, –120.3277'):
            self.assertReads(text, *DONNER, 'decimal degrees')

    def test_degrees_and_minutes(self):
        for text in ("N 39° 18.942' W 120° 19.662'", 'N39 18.942 W120 19.662', '39°18.942′N 120°19.662′W',
                     '39º18.942’N 120º19.662’W'):
            self.assertReads(text, *DONNER, 'degrees and minutes')

    def test_degrees_minutes_and_seconds(self):
        for text in ('39°18\'56.5"N 120°19\'39.7"W', '39°18′56.5″N 120°19′39.7″W', '39 18 56.5 N 120 19 39.7 W',
                     "39°18'56.5''N 120°19'39.7''W"):
            self.assertReads(text, 39.315694, -120.327694, 'degrees, minutes and seconds')

    def test_minutes_and_seconds_are_placed_by_their_marks(self):
        self.assertReads('37° 44" N 119° 35" W', 37.012222, -119.009722, 'degrees, minutes and seconds')

    def test_utm(self):
        for text in ('10S 727330 4355390', '10 727330mE 4355390mN', 'Zone 10S 727330E 4355390N', '10S 0727330 4355390',
                     'UTM 10S 727330 4355390', 'UTM Zone 10 727330 4355390'):
            self.assertReads(text, 39.318069, -120.36303, 'UTM')
        self.assertReads('34H 261878 6243186', -33.924866, 18.424062, 'UTM')        # southern hemisphere

    def test_usng(self):
        for text in ('10S GJ 27330 53919', '10SGJ2733053919', '10sgj 27330 53919', 'USNG 10S GJ 27330 53919',
                     'MGRS 10SGJ2733053919'):
            self.assertReads(text, 39.304833, -120.363521, 'USNG')
        self.assertReads('18S UJ 23487 06483', 38.889504, -77.035191, 'USNG')        # an even zone
        self.assertReads('10S GJ 2733 5391', 39.304747, -120.36353, 'USNG')           # to 10 m

    def test_each_form_caltopo_lists_reads_as_the_same_point(self):
        forms = ('UTM', 'USNG', 'decimal degrees', 'degrees and minutes', 'degrees, minutes and seconds')
        for (lat, lon), lines in CALTOPO_PANELS:
            for line, form in zip(lines, forms):
                self.assertReads(line, lat, lon, form, delta=HALF_A_SECOND)

    def test_every_example_in_the_message_reads_as_the_same_point(self):
        for example, form in zip(EXAMPLES, ('decimal degrees', 'degrees and minutes',
                                             'degrees, minutes and seconds', 'UTM', 'USNG')):
            self.assertReads(example, 37.7456, -119.5936, form)

    def test_runs_of_spaces_and_line_breaks_are_one_space(self):
        self.assertReads('10S' + ' ' * 5000 + '727330\n\n' + ' ' * 5000 + '4355390', 39.318069, -120.36303, 'UTM')

    def test_empty_box_is_no_point(self):
        self.assertIsNone(read_point('  '))

    def test_what_cannot_be_read(self):
        for text, message in (
                ('39.3157', UNREADABLE),
                ('Donner Summit', UNREADABLE),
                ('Meet at 39.3157, -120.3277 by the gate', UNREADABLE),
                ('https://www.google.com/maps/@39.3157,-120.3277,15z', UNREADABLE),
                ('Lat: ' * 20 + '39.3157 Long: -120.3277', UNREADABLE),           # over 100 characters
                ('10S' + ' ' * 5000 + '727330' + ' ' * 5000 + 'x', UNREADABLE),
                ('N 37.7456 W', UNREADABLE),
                ('95.5, -120.3', 'Latitude comes first, and runs from -90 to 90.'),
                ('-120.3277, 39.3157', 'Latitude comes first, and runs from -90 to 90.'),
                ('39.3, -190.5', 'Longitude runs from -180 to 180.'),
                ('9' * 90 + ', 5', 'Latitude comes first, and runs from -90 to 90.'),
                ('N39 N120', 'Give one latitude (N or S) and one longitude (E or W).'),
                ('39.3157, -120.3277 E', 'A minus sign and E disagree: use one or the other.'),
                ("39°18'10' N 120°19' W", 'Write degrees, then minutes, then seconds, such as 37°44\'44.2"N.'),
                ('61S 727330 4355390', 'UTM zones run from 1 to 60.'),
                ('10S GJ 273 53919', 'A USNG point needs as many easting digits as northing digits, '
                                     'such as 11S KB 71484 80756.'),
                ('10S GJ 273300 539190', 'A USNG point needs as many easting digits as northing digits, '
                                         'such as 11S KB 71484 80756.')):
            with self.assertRaises(NotAPoint, msg=text) as raised:
                read_point(text)
            self.assertEqual(str(raised.exception), message, msg=text)


class UsualAreaTestCase(TestCase):
    """Points outside the team's usual area, which the form warns of."""

    def test_inside_the_area(self):
        self.assertIsNone(area_warning(*DONNER))

    def test_each_edge_of_the_area(self):
        for inside, outside in (((32.41, -120.0), (32.39, -120.0)), ((46.39, -120.0), (46.41, -120.0)),
                                ((39.0, -124.79), (39.0, -124.81)), ((39.0, -114.01), (39.0, -113.99))):
            self.assertIsNone(area_warning(*inside), msg=inside)
            self.assertIsNotNone(area_warning(*outside), msg=outside)

    def test_outside_the_area_asks_for_a_check(self):
        # A sign slip on Donner Summit lands outside the area, as does the Grand Canyon.
        for point in ((39.3157, 120.3277), (-39.3157, -120.3277), GRAND_CANYON):
            self.assertEqual(area_warning(*point), OUTSIDE, msg=point)

    def test_area_comes_from_the_site_setting(self):
        preferences = global_preferences_registry.manager()
        usual = preferences['general__event_area']
        preferences['general__event_area'] = '32.4, 46.4, -124.8, -110.0'
        # Preferences are cached outside the test's database transaction, so put it back.
        self.addCleanup(preferences.__setitem__, 'general__event_area', usual)
        self.assertIsNone(area_warning(*GRAND_CANYON))

    def test_area_setting_takes_four_edges(self):
        self.assertEqual(area_edges(EventArea.default), [32.4, 46.4, -124.8, -114.0])
        for text in ('32.4, 46.4, -124.8', '46.4, 32.4, -124.8, -114.0', 'California'):
            with self.assertRaises(ValidationError, msg=text):
                EventArea().validate(text)


class EventFormLatLonTestCase(TestCase):
    """The Lat/Lon box on the event form: what it saves to the event's lat and lon."""

    def setUp(self):
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))

    def form(self, lat_lon, title='Snow travel'):
        start = timezone.localtime(self.event.start_at)
        finish = timezone.localtime(self.event.finish_at)
        return EventForm(instance=self.event, data={
            'title': title, 'type': self.event.type, 'location': self.event.location,
            'start_at_0': start.strftime('%Y-%m-%d'), 'start_at_1': start.strftime('%H:%M'),
            'finish_at_0': finish.strftime('%Y-%m-%d'), 'finish_at_1': finish.strftime('%H:%M'),
            'lat_lon': lat_lon,
        })

    def saved(self, form):
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.event.refresh_from_db()
        return self.event.lat, self.event.lon

    def test_saves_decimal_degrees_to_lat_and_lon(self):
        self.assertEqual(self.saved(self.form('39.3157, -120.3277')), ('39.3157', '-120.3277'))

    def test_saves_a_utm_point_converted(self):
        self.assertEqual(self.saved(self.form('10S 727330 4355390')), ('39.318069', '-120.36303'))

    def test_empty_box_saves_no_point(self):
        self.event.lat, self.event.lon = '39.3157', '-120.3277'
        self.event.save()
        self.assertEqual(self.saved(self.form('')), (None, None))

    def test_shows_the_saved_point(self):
        self.event.lat, self.event.lon = '39.3157', '-120.3277'
        self.assertEqual(EventForm(instance=self.event).initial['lat_lon'], '39.3157, -120.3277')

    def test_unreadable_text_is_an_error(self):
        form = self.form('Donner Summit')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lat_lon'], [UNREADABLE])

    def test_point_outside_the_area_saves(self):
        self.assertEqual(self.saved(self.form('36.0544, -112.1401')), ('36.0544', '-112.1401'))

    def test_untouched_point_is_kept_as_stored(self):
        for stored in (('39.3150', '-120.3270'), ('not', 'a point')):
            self.event.lat, self.event.lon = stored
            self.event.save()
            self.assertEqual(self.saved(self.form('{}, {}'.format(*stored), title='Snow travel 2')), stored)


class EventLatLonPageTestCase(TestCase):
    """The event pages, and the reading the form asks for as a member fills in the box."""

    def setUp(self):
        self.member = Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T')
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))
        self.client.force_login(self.member)

    def reading(self, text):
        return self.client.post('/event/lat_lon/', {'text': text}).json()

    def test_edit_and_add_pages_have_one_lat_lon_box(self):
        for url in ('/event/{}/edit/'.format(self.event.id), '/event/add'):
            response = self.client.get(url)
            self.assertContains(response, 'type="text" name="lat_lon"', msg_prefix=url)
            self.assertContains(response, "fetch('/event/lat_lon/'", msg_prefix=url)
            self.assertNotContains(response, 'name="lat"', msg_prefix=url)
            self.assertNotContains(response, 'name="lon"', msg_prefix=url)
            self.assertNotContains(response, 'geopicker', msg_prefix=url)

    def test_event_page_shows_the_point_to_copy(self):
        self.event.lat, self.event.lon = '39.3157', '-120.3277'
        self.event.save()
        response = self.client.get('/event/{}/'.format(self.event.id))
        self.assertContains(response, '<strong>Lat/Lon:</strong> <span id="event-lat-lon">39.3157, -120.3277</span>')
        self.assertContains(response, '<a href="#" id="copy-lat-lon" role="button" aria-label="Copy Lat/Lon">\n'
                                      '        <i class="fa fa-copy"></i> Copy</a>')
        self.assertNotContains(response, '<strong>Lat:</strong>')

    def test_event_page_without_a_whole_point_shows_none(self):
        for lat in (None, '39.3157'):
            self.event.lat = lat
            self.event.save()
            response = self.client.get('/event/{}/'.format(self.event.id))
            self.assertNotContains(response, 'Lat/Lon:', msg_prefix=str(lat))
            self.assertNotContains(response, 'id="copy-lat-lon"', msg_prefix=str(lat))

    def test_reading_converts_a_utm_point(self):
        self.assertEqual(self.reading('10S 727330 4355390'), {'value': '39.318069, -120.36303',
                                                             'note': 'Converted from UTM.', 'warning': None})

    def test_reading_warns_of_a_point_outside_the_area(self):
        self.assertEqual(self.reading('39.45817, -110.97440'), {'value': '39.45817, -110.9744', 'note': '',
                                                               'warning': OUTSIDE})

    def test_reading_reports_what_cannot_be_read(self):
        self.assertEqual(self.reading('Donner Summit'), {'error': UNREADABLE})

    def test_reading_an_empty_box(self):
        self.assertEqual(self.reading(''), {'value': ''})

    def test_reading_needs_a_signed_in_member_and_a_post(self):
        self.assertEqual(self.client.get('/event/lat_lon/').status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post('/event/lat_lon/', {'text': '39.3157, -120.3277'}).status_code, 302)
