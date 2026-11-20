from datetime import date, datetime, time, timedelta

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
    date(2026, 3, 7): ('06:30:22', '18:07:18', '18:33:34'),
    date(2026, 3, 8): ('07:28:54', '19:08:17', '19:34:31'),       # the clocks go forward
    date(2026, 10, 31): ('07:32:21', '18:09:39', '18:36:50'),
    date(2026, 11, 1): ('06:33:24', '17:08:34', '17:35:47'),      # the clocks go back
}


def local(day, hour, minute=0):
    return timezone.make_aware(datetime(day.year, day.month, day.day, hour, minute))


class SunTimesTestCase(TestCase):
    def test_within_a_minute_of_jpl(self):
        for day, expected in JPL.items():
            found = sun_times(*map(float, MOUNT_DIABLO), day)
            for name, text in zip(('sunrise', 'sunset', 'dark_by'), expected):
                jpl = timezone.make_aware(datetime.combine(day, time.fromisoformat(text)))
                self.assertLessEqual(abs((found[name] - jpl).total_seconds()), 60, (day, name))
                self.assertEqual(found[name].second, 0)

    def test_none_where_the_sun_does_not_rise_or_set(self):
        self.assertIsNone(sun_times(80.0, -120.0, date(2026, 12, 21)))       # polar night
        self.assertIsNone(sun_times(80.0, -120.0, date(2026, 6, 21)))        # midnight sun


class EventSunPageTestCase(TestCase):
    def setUp(self):
        self.client.force_login(Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T'))

    def page(self, start, lat_lon=MOUNT_DIABLO):
        event = Event.objects.create(type='training', title='Night navigation', location='Mount Diablo',
                                     start_at=start, finish_at=start, lat=lat_lon[0], lon=lat_lon[1])
        return self.client.get('/event/{}/'.format(event.id))

    def assertShows(self, response, sunrise, sunset, dark_by):
        for label, time_text in (('Sunrise', sunrise), ('Sunset', sunset), ('Dark by', dark_by)):
            self.assertContains(response, '<span class="sr-only">{}</span> {}</span>'.format(label, time_text))

    def test_event_page_shows_the_sun_on_the_start_day(self):
        self.assertShows(self.page(local(date(2026, 12, 21), 9)), '07:20', '16:52', '17:22')
        response = self.page(local(date(2026, 6, 21), 9))
        self.assertShows(response, '05:46', '20:33', '21:05')
        self.assertContains(response, '<strong title="On Jun 21, for a flat horizon: the sun goes behind ridges and '
                                      'canyon walls earlier.">Daylight:</strong>')
        for tooltip, symbol, label in (('Sunrise', '&#x2600;&#xFE0F;&#x2191;', 'Sunrise'),
                                       ('Sunset', '&#x2600;&#xFE0F;&#x2193;', 'Sunset'),
                                       ('Dark by: the end of civil twilight', '&#x1F319;', 'Dark by')):
            self.assertContains(response, '<span title="{}"><span aria-hidden="true">{}</span><span class="sr-only">{}</span>'
                                .format(tooltip, symbol, label))
        page = response.content.decode()
        self.assertLess(page.index('<details id="location-details"'), page.index('Daylight:</strong>'))
        self.assertLess(page.index('Daylight:</strong>'), page.index('<strong>Weather:</strong>'))

    def test_the_clocks_changing(self):
        # The clocks change at 2 a.m., before sunrise, so the whole day is on the new time.
        for day, times in ((date(2026, 3, 7), ('06:31', '18:07', '18:34')), (date(2026, 3, 8), ('07:29', '19:08', '19:35')),
                           (date(2026, 10, 31), ('07:33', '18:09', '18:37')), (date(2026, 11, 1), ('06:34', '17:08', '17:36'))):
            self.assertShows(self.page(local(day, 9)), *times)

    def test_a_late_start_reads_the_local_day(self):
        # At 23:30 here it's already the next day in UTC. Near the equinox sunrise moves a minute or more a day.
        day = date(2027, 3, 20)
        this_day, next_day = (sun_times(*map(float, MOUNT_DIABLO), d) for d in (day, day + timedelta(days=1)))
        self.assertNotEqual(this_day['sunrise'].time(), next_day['sunrise'].time())
        response = self.page(local(day, 23, 30))
        self.assertContains(response, 'On Mar 20, for a flat horizon')
        self.assertContains(response, '<span class="sr-only">Sunrise</span> {:%H:%M}</span>'.format(this_day['sunrise']))

    def test_no_sun_line_without_a_whole_point(self):
        for lat_lon in ((None, None), ('37.8817', None), ('80', '-120')):
            self.assertNotContains(self.page(local(date(2026, 12, 21), 9), lat_lon), 'Daylight:', msg_prefix=str(lat_lon))
