from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from main.lib.sun import sun_times
from main.models import Event, Member

# Public places only.
MOUNT_DIABLO = ('37.8817', '-121.9142')
# Sunrise, sunset and the end of civil twilight at Mount Diablo's summit, from Skyfield 1.55 with
# JPL's DE421 ephemeris, run separately, so these tests check astral against an independent source.
JPL = {
    date(2026, 6, 21): ('05:45:44', '20:33:20', '21:04:45'),
    date(2026, 12, 21): ('07:19:46', '16:52:00', '17:21:29'),
}


def local(day, hour, minute=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hour, minute))


class SunTimesTestCase(TestCase):
    def test_within_a_minute_of_jpl(self):
        for day, expected in JPL.items():
            found = sun_times(*MOUNT_DIABLO, day)
            for name, text in zip(('sunrise', 'sunset', 'dark_by'), expected):
                jpl = timezone.make_aware(datetime.combine(day, time.fromisoformat(text)))
                self.assertLessEqual(abs((found[name] - jpl).total_seconds()), 60, (day, name))
                self.assertEqual(found[name].second, 0)

    def test_none_where_the_sun_does_not_rise_or_the_point_cannot_be_read(self):
        self.assertIsNone(sun_times('80', '-120', date(2026, 12, 21)))
        self.assertIsNone(sun_times('north', '-120', date(2026, 12, 21)))


class EventSunPageTestCase(TestCase):
    def setUp(self):
        self.client.force_login(Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T'))

    def page(self, start, lat_lon=MOUNT_DIABLO):
        event = Event.objects.create(type='training', title='Night navigation', location='Mount Diablo',
                                     start_at=start, finish_at=start, lat=lat_lon[0], lon=lat_lon[1])
        return self.client.get('/event/{}/'.format(event.id))

    def test_event_page_shows_the_sun_on_the_start_day(self):
        def shown(response, sunrise, sunset, dark_by):
            for label, time_text in (('Sunrise', sunrise), ('Sunset', sunset), ('Dark by', dark_by)):
                self.assertContains(response, '<span class="sr-only">{}</span> {}</span>'.format(label, time_text))
        shown(self.page(local(date(2026, 12, 21), 9)), '07:20', '16:52', '17:22')
        response = self.page(local(date(2026, 6, 21), 9))
        shown(response, '05:46', '20:33', '21:05')
        self.assertContains(response, '<strong title="On Jun 21, for a flat horizon: the sun goes behind ridges and '
                                      'canyon walls earlier.">Daylight:</strong>')
        for tooltip in ('Sunrise', 'Sunset', 'Dark by: the end of civil twilight'):
            self.assertContains(response, '<span title="{}">'.format(tooltip))
        page = response.content.decode()
        self.assertLess(page.index('<strong>Lat/Lon:</strong>'), page.index('Daylight:</strong>'))
        self.assertLess(page.index('Daylight:</strong>'), page.index('<strong>Weather:</strong>'))

    def test_a_late_start_reads_the_local_day(self):
        self.assertContains(self.page(local(date(2026, 12, 21), 23, 30)), 'On Dec 21, for a flat horizon')

    def test_no_sun_line_without_a_whole_point(self):
        for lat_lon in ((None, None), ('37.8817', None), ('80', '-120')):
            self.assertNotContains(self.page(local(date(2026, 12, 21), 9), lat_lon), 'Daylight:', msg_prefix=str(lat_lon))
