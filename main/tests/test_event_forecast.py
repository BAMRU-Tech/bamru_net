from datetime import date, datetime, timedelta
from unittest import mock

import requests
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from main.lib import forecast
from main.lib.forecast import USER_AGENT, forecast_days
from main.models import Event, Member

# Public places only. The tests never call the National Weather Service: each answer is mocked.
MOUNT_DIABLO = (37.8817, -121.9142)
FORECAST_URL = 'https://api.weather.gov/gridpoints/MTR/103,106/forecast'


def period(start, daytime, temperature, precip, wind='6 mph', direction='ESE', summary='Light Rain Likely'):
    return {'startTime': start, 'isDaytime': daytime, 'temperature': temperature,
            'probabilityOfPrecipitation': {'unitCode': 'wmoUnit:percent', 'value': precip},
            'windSpeed': wind, 'windDirection': direction, 'shortForecast': summary}


# The periods as the service gave them for Mount Diablo on 20 Nov 2026, starting in the early morning.
PERIODS = [
    period('2026-11-20T01:00:00-08:00', False, 34, 69, '6 mph', 'WSW', 'Light Rain Likely'),            # Overnight
    period('2026-11-20T06:00:00-08:00', True, 41, 78, '7 mph', 'NW', 'Light Rain then Partly Sunny'),   # Friday
    period('2026-11-20T18:00:00-08:00', False, 35, None, '5 mph', 'NE', 'Mostly Clear'),                # Friday Night
    period('2026-11-21T06:00:00-08:00', True, 41, 64, '5 to 10 mph', 'ESE', 'Light Rain Likely'),       # Saturday
    period('2026-11-21T18:00:00-08:00', False, 33, 20),                                                  # Saturday Night
    period('2026-11-22T06:00:00-08:00', True, 50, 0, '10 mph', 'N', 'Sunny'),                            # Sunday
]


def service_answers(periods=PERIODS, problem=None):
    """requests.get as the service would answer: the point's grid, then its forecast, or `problem` raised."""
    def get(url, **kwargs):
        if problem:
            raise problem
        response = mock.Mock()
        response.json.return_value = {'properties': {'forecast': FORECAST_URL} if '/points/' in url else {'periods': periods}}
        return response
    return mock.patch.object(forecast.requests, 'get', mock.Mock(side_effect=get))


class ForecastDaysTestCase(TestCase):
    def setUp(self):
        cache.clear()

    def test_each_day_high_low_precip_and_wind(self):
        with service_answers():
            days = forecast_days(*MOUNT_DIABLO, date(2026, 11, 20), date(2026, 11, 22))
        self.assertEqual(days, [
            {'date': '2026-11-20', 'label': 'Fri Nov 20', 'high': 41, 'low': 35, 'precip': 78,
             'wind': '7 mph NW', 'summary': 'Light Rain then Partly Sunny'},
            {'date': '2026-11-21', 'label': 'Sat Nov 21', 'high': 41, 'low': 33, 'precip': 64,
             'wind': '5 to 10 mph ESE', 'summary': 'Light Rain Likely'},
            {'date': '2026-11-22', 'label': 'Sun Nov 22', 'high': 50, 'low': None, 'precip': 0,
             'wind': '10 mph N', 'summary': 'Sunny'},
        ])

    def test_only_the_events_days(self):
        with service_answers():
            self.assertEqual([d['date'] for d in forecast_days(*MOUNT_DIABLO, date(2026, 11, 21), date(2026, 11, 21))],
                             ['2026-11-21'])
            self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 12, 1), date(2026, 12, 3)), [])

    def test_an_overnight_period_is_the_night_before(self):
        with service_answers():
            self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 11, 19), date(2026, 11, 19)), [
                {'date': '2026-11-19', 'label': 'Thu Nov 19', 'high': None, 'low': 34, 'precip': 69,
                 'wind': '6 mph WSW', 'summary': 'Light Rain Likely'}])

    def test_asks_with_the_sites_name_and_keeps_the_answer(self):
        with service_answers() as get:
            forecast_days(*MOUNT_DIABLO, date(2026, 11, 20), date(2026, 11, 20))
            forecast_days(*MOUNT_DIABLO, date(2026, 11, 21), date(2026, 11, 21))
        self.assertEqual([c.args[0] for c in get.call_args_list],
                         ['https://api.weather.gov/points/37.8817,-121.9142', FORECAST_URL])
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)

    def test_no_answer_gives_no_days_and_is_not_asked_again_at_once(self):
        for problem in (requests.Timeout(), requests.HTTPError('404 outside the US'), requests.ConnectionError()):
            cache.clear()
            with service_answers(problem=problem) as get:
                self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 11, 20), date(2026, 11, 20)), [], problem)
                self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 11, 20), date(2026, 11, 20)), [], problem)
            self.assertEqual(get.call_count, 1, problem)


class EventForecastPageTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T'))

    def event(self, first_day, days=1, point=MOUNT_DIABLO):
        start = timezone.make_aware(datetime(first_day.year, first_day.month, first_day.day, 9))
        return Event.objects.create(type='training', title='Snow camp', location='Mount Diablo', start_at=start,
                                    finish_at=start + timedelta(days=days - 1, hours=8),
                                    lat=point and str(point[0]), lon=point and str(point[1]))

    def test_the_forecast_for_each_day_of_the_event(self):
        event = self.event(date(2026, 11, 20), days=2)
        with service_answers():
            days = self.client.get('/event/{}/forecast/'.format(event.id)).json()['days']
        self.assertEqual([d['date'] for d in days], ['2026-11-20', '2026-11-21'])

    def test_no_forecast_without_a_whole_point(self):
        event = self.event(date(2026, 11, 20), point=None)
        with service_answers() as get:
            self.assertEqual(self.client.get('/event/{}/forecast/'.format(event.id)).json(), {'days': []})
        get.assert_not_called()

    def test_the_forecast_needs_a_signed_in_member(self):
        event = self.event(date(2026, 11, 20))
        self.client.logout()
        with service_answers() as get:
            self.assertEqual(self.client.get('/event/{}/forecast/'.format(event.id)).status_code, 302)
        get.assert_not_called()

    def test_the_page_asks_only_for_an_event_within_the_forecast(self):
        today = timezone.localdate()
        for first_day, days, asks in ((today + timedelta(days=2), 1, True), (today - timedelta(days=3), 5, True),
                                      (today - timedelta(days=10), 1, False), (today + timedelta(days=10), 1, False)):
            event = self.event(first_day, days)
            response = self.client.get('/event/{}/'.format(event.id))
            self.assertContains(response, 'NOAA Forecast</a>')
            check = self.assertContains if asks else self.assertNotContains
            check(response, '<span id="event-forecast"></span>', msg_prefix=str(first_day))
            check(response, "$.getJSON('/event/{}/forecast/'".format(event.id), msg_prefix=str(first_day))
