from datetime import timedelta

from django.forms import CheckboxInput
from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.lib.lat_long import EXAMPLES, NotAPoint, outside_usual_area, read_point
from main.models import Event, Member
from main.views.event_views import EventForm

# Public places only. Donner Summit is inside the team's usual area; the Grand Canyon is outside it.
DONNER = (39.3157, -120.3277)
GRAND_CANYON = (36.0544, -112.1401)
# Within about 2 m. The UTM and USNG answers below come from pyproj 3.8 and the mgrs package,
# run separately, so these tests check the conversions against an independent source.
CLOSE = 2e-5


class ReadPointTestCase(TestCase):
    """Every form the Lat/Long box reads, and what it reads each as."""

    def assertReads(self, text, lat, lon, form):
        point = read_point(text)
        self.assertAlmostEqual(point.lat, lat, delta=CLOSE, msg=text)
        self.assertAlmostEqual(point.lon, lon, delta=CLOSE, msg=text)
        self.assertEqual(point.form, form, msg=text)

    def test_decimal_degrees(self):
        for text in ('39.3157, -120.3277', '39.3157 -120.3277', '39.3157,-120.3277',
                     '39.3157 N, 120.3277 W', 'N39.3157 W120.3277', '39.3157°N 120.3277°W',
                     'W120.3277 N39.3157', 'Lat: 39.3157 Long: -120.3277', '39.3157, −120.3277'):
            self.assertReads(text, *DONNER, 'decimal degrees')

    def test_degrees_and_minutes(self):
        for text in ("N 39° 18.942' W 120° 19.662'", 'N39 18.942 W120 19.662', '39°18.942′N 120°19.662′W'):
            self.assertReads(text, *DONNER, 'degrees and minutes')

    def test_degrees_minutes_and_seconds(self):
        for text in ('39°18\'56.5"N 120°19\'39.7"W', '39°18′56.5″N 120°19′39.7″W', '39 18 56.5 N 120 19 39.7 W'):
            self.assertReads(text, 39.315694, -120.327694, 'degrees, minutes and seconds')

    def test_utm(self):
        for text in ('10S 727330 4355390', '10 727330mE 4355390mN', 'Zone 10S 727330E 4355390N', '10S 0727330 4355390'):
            self.assertReads(text, 39.318069, -120.36303, 'UTM')
        self.assertReads('11S 271234 4180567', 37.743829, -119.596383, 'UTM')
        self.assertReads('34H 261878 6243186', -33.924866, 18.424062, 'UTM')        # southern hemisphere

    def test_usng(self):
        for text in ('10S GJ 27330 53919', '10SGJ2733053919', '10sgj 27330 53919'):
            self.assertReads(text, 39.304833, -120.363521, 'USNG')
        self.assertReads('11S KB 71234 80567', 37.743833, -119.596378, 'USNG')
        self.assertReads('18S UJ 23487 06483', 38.889504, -77.035191, 'USNG')        # an even zone
        self.assertReads('10S GJ 2733 5391', 39.304747, -120.36353, 'USNG')           # to 10 m

    def test_map_links(self):
        for link in ('https://www.google.com/maps/place/Donner+Summit/@39.31,-120.33,15z/data=!3m1!4b1!4m6!3m5'
                     '!1s0x0:0x0!8m2!3d39.3157!4d-120.3277',
                     'https://www.google.com/maps/@39.3157,-120.3277,15z',
                     'https://www.google.com/maps/search/39.3157,+-120.3277',
                     'https://caltopo.com/map.html#ll=39.3157,-120.3277&z=14&b=mbt',
                     'https://maps.apple.com/?ll=39.3157,-120.3277&q=Pin'):
            self.assertReads(link, *DONNER, 'a map link')

    def test_every_example_in_the_message_reads_as_the_same_point(self):
        for example, form in zip(EXAMPLES, ('decimal degrees', 'degrees and minutes',
                                             'degrees, minutes and seconds', 'UTM', 'USNG')):
            self.assertReads(example, 37.7456, -119.5936, form)

    def test_empty_box_is_no_point(self):
        self.assertIsNone(read_point('  '))

    def test_what_cannot_be_read(self):
        unreadable = ('Enter a point in any of these forms: 37.7456, -119.5936; N 37° 44.736\' W 119° 35.616\'; '
                      '37°44\'44.2"N 119°35\'37.0"W; UTM 11S 271485 4180757; or USNG 11S KB 71484 80756. '
                      'A map link works too.')
        for text, message in (
                ('39.3157', unreadable),
                ('Donner Summit', unreadable),
                ('95.5, -120.3', 'Latitude runs from -90 to 90.'),
                ('39.3, -190.5', 'Longitude runs from -180 to 180.'),
                ('N39 N120', 'Give one latitude (N or S) and one longitude (E or W).'),
                ('61S 727330 4355390', 'UTM zones run from 1 to 60.'),
                ('10S GJ 273 53919', 'A USNG point needs as many easting digits as northing digits, '
                                     'such as 11S KB 71234 80567.'),
                ('https://maps.app.goo.gl/abc123', "This link doesn't hold a point. Short links, such as "
                 "maps.app.goo.gl ones, can't be read: open the link and copy the coordinates instead.")):
            with self.assertRaisesMessage(NotAPoint, message):
                read_point(text)

    def test_longitude_first_suggests_the_swap(self):
        with self.assertRaises(NotAPoint) as raised:
            read_point('-120.3277, 39.3157')
        self.assertEqual(str(raised.exception), 'Latitude comes first. Did you mean 39.3157, -120.3277?')
        self.assertEqual(raised.exception.suggestion, '39.3157, -120.3277')


class UsualAreaTestCase(TestCase):
    """Points outside the team's usual area, as the form questions them."""

    def test_inside_the_area(self):
        self.assertIsNone(outside_usual_area(*DONNER))

    def test_missing_minus_sign_suggests_the_fix(self):
        problem = outside_usual_area(39.3157, 120.3277)
        self.assertEqual(problem.message, 'Did you mean 39.3157, -120.3277? The point as typed is outside '
                                          'the area the team usually works in.')
        self.assertEqual(problem.suggestion, '39.3157, -120.3277')

    def test_wrong_latitude_sign_suggests_the_fix(self):
        self.assertEqual(outside_usual_area(-39.3157, -120.3277).suggestion, '39.3157, -120.3277')
        self.assertEqual(outside_usual_area(-39.3157, 120.3277).suggestion, '39.3157, -120.3277')

    def test_far_from_the_area(self):
        problem = outside_usual_area(*GRAND_CANYON)
        self.assertEqual(problem.message, 'This point is outside the area the team usually works in. '
                                          'Check it on a map.')
        self.assertIsNone(problem.suggestion)

    def test_area_comes_from_the_site_preferences(self):
        preferences = global_preferences_registry.manager()
        usual_east = preferences['general__event_area_east']
        preferences['general__event_area_east'] = -110.0
        # Preferences are cached outside the test's database transaction, so put it back.
        self.addCleanup(preferences.__setitem__, 'general__event_area_east', usual_east)
        self.assertIsNone(outside_usual_area(*GRAND_CANYON))


class EventFormLatLongTestCase(TestCase):
    """The Lat/Long box on the event form: what it saves to the event's lat and lon."""

    def setUp(self):
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))

    def form(self, lat_long, point_is_right=False):
        start = timezone.localtime(self.event.start_at)
        finish = timezone.localtime(self.event.finish_at)
        data = {
            'title': self.event.title, 'type': self.event.type, 'location': self.event.location,
            'start_at_0': start.strftime('%Y-%m-%d'), 'start_at_1': start.strftime('%H:%M'),
            'finish_at_0': finish.strftime('%Y-%m-%d'), 'finish_at_1': finish.strftime('%H:%M'),
            'lat_long': lat_long,
        }
        if point_is_right:
            data['point_is_right'] = 'on'
        return EventForm(data=data, instance=self.event)

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
        self.event.save()
        self.assertEqual(EventForm(instance=self.event).initial['lat_long'], '39.3157, -120.3277')

    def test_unreadable_text_is_an_error(self):
        form = self.form('Donner Summit')
        self.assertFalse(form.is_valid())
        self.assertIn('Enter a point in any of these forms', form.errors['lat_long'][0])

    def test_point_outside_the_area_is_questioned(self):
        form = self.form('39.3157, 120.3277')
        self.assertFalse(form.is_valid())
        self.assertIn('Did you mean 39.3157, -120.3277?', form.errors['point_is_right'][0])
        self.assertIsInstance(form.fields['point_is_right'].widget, CheckboxInput)

    def test_questioned_point_saves_once_confirmed(self):
        self.assertEqual(self.saved(self.form('36.0544, -112.1401', point_is_right=True)),
                         ('36.0544', '-112.1401'))

    def test_point_already_saved_is_not_questioned_again(self):
        self.event.lat, self.event.lon = '36.0544', '-112.1401'
        self.event.save()
        self.assertEqual(self.saved(self.form('36.0544, -112.1401')), ('36.0544', '-112.1401'))


class EventLatLongPageTestCase(TestCase):
    """The event edit page and the reading it asks for as a member fills in the box."""

    def setUp(self):
        self.member = Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T')
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))

    def test_edit_page_has_one_lat_long_box(self):
        self.client.force_login(self.member)
        response = self.client.get('/event/{}/edit/'.format(self.event.id))
        self.assertContains(response, 'Lat/Long')
        self.assertContains(response, 'type="text" name="lat_long"')
        self.assertNotContains(response, 'name="lat"')
        self.assertNotContains(response, 'name="lon"')
        self.assertNotContains(response, 'geopicker')

    def test_event_page_shows_the_point_to_copy(self):
        self.event.lat, self.event.lon = '39.3157', '-120.3277'
        self.event.save()
        self.client.force_login(self.member)
        response = self.client.get('/event/{}/'.format(self.event.id))
        self.assertContains(response, '<strong>Lat/Long:</strong> <span id="event-lat-long">39.3157, -120.3277</span>',
                            html=False)
        self.assertContains(response, 'id="copy-lat-long"')
        self.assertNotContains(response, '<strong>Lat:</strong>')

    def test_event_page_without_a_point_shows_none(self):
        self.client.force_login(self.member)
        response = self.client.get('/event/{}/'.format(self.event.id))
        self.assertNotContains(response, 'Lat/Long:')
        self.assertNotContains(response, 'id="copy-lat-long"')

    def test_reading_converts_a_utm_point(self):
        self.client.force_login(self.member)
        response = self.client.post('/event/lat_long/', {'text': '10S 727330 4355390'})
        self.assertEqual(response.json(), {'value': '39.318069, -120.36303', 'form': 'UTM',
                                           'warning': None, 'suggestion': None})

    def test_reading_questions_a_wrong_sign(self):
        self.client.force_login(self.member)
        response = self.client.post('/event/lat_long/', {'text': '39.3157, 120.3277'})
        self.assertEqual(response.json()['suggestion'], '39.3157, -120.3277')
        self.assertIn('Did you mean 39.3157, -120.3277?', response.json()['warning'])

    def test_reading_reports_what_cannot_be_read(self):
        self.client.force_login(self.member)
        response = self.client.post('/event/lat_long/', {'text': 'Donner Summit'})
        self.assertIn('Enter a point in any of these forms', response.json()['error'])

    def test_reading_needs_a_signed_in_member(self):
        response = self.client.post('/event/lat_long/', {'text': '39.3157, -120.3277'})
        self.assertEqual(response.status_code, 302)
