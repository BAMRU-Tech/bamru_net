from datetime import timedelta

from django.forms import CheckboxInput
from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.models import Event, Member
from main.views.event_views import EventForm

# Public places only: Donner Summit is inside the team's usual area, the Grand Canyon outside it.
DONNER = ('39.3157', '-120.3277')
GRAND_CANYON = ('36.0544', '-112.1401')


class EventPointFieldsTestCase(TestCase):
    """The Latitude and Longitude boxes on the event form."""

    def setUp(self):
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))

    def form(self, lat='', lon='', point_is_right=False):
        start = timezone.localtime(self.event.start_at)
        finish = timezone.localtime(self.event.finish_at)
        data = {
            'title': self.event.title, 'type': self.event.type, 'location': self.event.location,
            'start_at_0': start.strftime('%Y-%m-%d'), 'start_at_1': start.strftime('%H:%M'),
            'finish_at_0': finish.strftime('%Y-%m-%d'), 'finish_at_1': finish.strftime('%H:%M'),
            'lat': lat, 'lon': lon,
        }
        if point_is_right:
            data['point_is_right'] = 'on'
        return EventForm(data=data, instance=self.event)

    def saved_point(self, form):
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.event.refresh_from_db()
        return self.event.lat, self.event.lon

    def test_no_point_saves_nothing(self):
        self.assertEqual(self.saved_point(self.form()), (None, None))

    def test_point_in_the_area_saves_as_typed(self):
        self.assertEqual(self.saved_point(self.form(*DONNER)), DONNER)

    def test_point_copied_from_a_map_fills_both(self):
        self.assertEqual(self.saved_point(self.form(lat='39.3157, -120.3277')), DONNER)
        self.assertEqual(self.saved_point(self.form(lat='39.3157 -120.3277')), DONNER)

    def test_google_maps_link_fills_both(self):
        link = 'https://www.google.com/maps/@39.3157,-120.3277,15z'
        self.assertEqual(self.saved_point(self.form(lat=link)), DONNER)

    def test_one_without_the_other_is_an_error(self):
        form = self.form(lat='39.3157')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lon'], ['Enter both latitude and longitude, or neither.'])

    def test_not_decimal_degrees_is_an_error(self):
        form = self.form(lat='39°18′57″N', lon='-120.3277')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lat'], ['Enter decimal degrees, such as 37.7456.'])

    def test_swapped_latitude_and_longitude_is_an_error(self):
        form = self.form(lat='-120.3277', lon='39.3157')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lat'], ['Latitude and longitude look swapped.'])

    def test_out_of_range_is_an_error(self):
        form = self.form(lat='95.5', lon='-120.3277')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lat'], ['Enter a latitude from -90 to 90.'])
        form = self.form(lat='39.3157', lon='-200.5')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['lon'], ['Enter a longitude from -180 to 180.'])

    def test_missing_minus_sign_is_questioned_with_the_fix(self):
        form = self.form(lat='39.3157', lon='120.3277')
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['point_is_right'], [
            'Did you mean 39.3157, -120.3277? The point as typed is outside the area the team '
            'usually works in.'])
        self.assertIsInstance(form.fields['point_is_right'].widget, CheckboxInput)

    def test_wrong_latitude_sign_is_questioned_with_the_fix(self):
        form = self.form(lat='-39.3157', lon='-120.3277')
        self.assertFalse(form.is_valid())
        self.assertIn('Did you mean 39.3157, -120.3277?', form.errors['point_is_right'][0])

    def test_point_far_from_the_area_is_questioned(self):
        form = self.form(*GRAND_CANYON)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors['point_is_right'], [
            'This point is outside the area the team usually works in. Check it on a map.'])

    def test_questioned_point_saves_once_confirmed(self):
        self.assertEqual(self.saved_point(self.form(*GRAND_CANYON, point_is_right=True)), GRAND_CANYON)

    def test_point_already_saved_is_not_questioned_again(self):
        self.event.lat, self.event.lon = GRAND_CANYON
        self.event.save()
        self.assertEqual(self.saved_point(self.form(*GRAND_CANYON)), GRAND_CANYON)

    def test_area_comes_from_the_site_preferences(self):
        preferences = global_preferences_registry.manager()
        usual_east = preferences['general__event_area_east']
        preferences['general__event_area_east'] = -110.0
        # Preferences are cached outside the test's database transaction, so put it back.
        self.addCleanup(preferences.__setitem__, 'general__event_area_east', usual_east)
        self.assertEqual(self.saved_point(self.form(*GRAND_CANYON)), GRAND_CANYON)


class EventEditPagePointTestCase(TestCase):
    """The event edit page, as a member sees it."""

    def setUp(self):
        self.member = Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T')
        self.client.force_login(self.member)
        start = timezone.localtime().replace(hour=9, minute=0, second=0, microsecond=0)
        self.event = Event.objects.create(
            type='training', title='Snow travel', location='Donner Summit',
            start_at=start, finish_at=start + timedelta(hours=8))
        self.url = '/event/{}/edit/'.format(self.event.id)
        self.data = {
            'title': 'Snow travel', 'type': 'training', 'location': 'Donner Summit',
            'start_at_0': start.strftime('%Y-%m-%d'), 'start_at_1': '09:00',
            'finish_at_0': start.strftime('%Y-%m-%d'), 'finish_at_1': '17:00',
        }

    def test_edit_page_shows_the_point_boxes(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Latitude')
        self.assertContains(response, 'type="text" name="lat"')
        self.assertContains(response, 'type="text" name="lon"')
        self.assertContains(response, 'type="hidden" name="point_is_right"')
        self.assertNotContains(response, 'geopicker')

    def test_questioned_point_shows_the_checkbox(self):
        response = self.client.post(self.url, dict(self.data, lat='39.3157', lon='120.3277'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Did you mean 39.3157, -120.3277?')
        self.assertContains(response, 'type="checkbox" name="point_is_right"')
        self.assertContains(response, 'This point is right: save it anyway')

    def test_confirmed_point_saves_and_shows_on_the_event(self):
        response = self.client.post(self.url, dict(self.data, lat='39.3157', lon='120.3277',
                                                   point_is_right='on'))
        self.assertRedirects(response, '/event/{}/'.format(self.event.id), fetch_redirect_response=False)
        self.event.refresh_from_db()
        self.assertEqual((self.event.lat, self.event.lon), ('39.3157', '120.3277'))
