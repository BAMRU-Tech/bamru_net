import re
from datetime import date, datetime, timedelta
from unittest import mock

import requests
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from main.lib import forecast
from main.lib.forecast import (FEATURE_FLAGS, RETRY_AFTER, USER_AGENT, fahrenheit, fahrenheit_with_unit, forecast_days,
                               temperature_band, weather_symbol, wind_mph_from_text, wind_mph_with_unit)
from main.models import Event, Member
from main.lib.lookups import cache
from main.tests.lookup_support import FetchedAtOnce, in_memory

# Public places only. The tests never call the National Weather Service: each answer is mocked.
MOUNT_DIABLO = (37.8817, -121.9142)
FORECAST_URL = 'https://api.weather.gov/gridpoints/MTR/103,106/forecast'
RAIN, SNOW, FOG = '\U0001f327\ufe0f', '\U0001f328\ufe0f', '\U0001f32b\ufe0f'


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


def in_the_new_format(period):
    """The period as the API gives it with the feature flags set: temperature in °C and wind in km/h,
    each a value with its unit code, a range for "5 to 10 mph"."""
    speeds = [int(mph) * 1.609344 for mph in period['windSpeed'].removesuffix(' mph').split(' to ')]
    wind = {'value': speeds[0]} if len(speeds) == 1 else {'minValue': speeds[0], 'maxValue': speeds[1]}
    return dict(period, temperature={'unitCode': 'wmoUnit:degC', 'value': (period['temperature'] - 32) * 5 / 9},
                windSpeed=dict(wind, unitCode='wmoUnit:km_h-1'))


PERIODS_IN_THE_NEW_FORMAT = [in_the_new_format(p) for p in PERIODS]


def service_answers(periods=None, problem=None, with_units_problem=None):
    """requests.get as the service would answer: the point's grid, then its forecast, with units when the
    feature flags ask for them and in the deprecated format otherwise; or `periods` whatever is asked, or
    `problem` raised, or `with_units_problem` raised only when the flags are sent."""
    def get(url, headers, **kwargs):
        with_units = 'Feature-Flags' in headers
        if problem or (with_units and with_units_problem):
            raise problem or with_units_problem
        response = mock.Mock()
        response.json.return_value = {'properties': {'forecast': FORECAST_URL} if '/points/' in url else {
            'periods': periods or (PERIODS_IN_THE_NEW_FORMAT if with_units else PERIODS)}}
        return response
    return mock.patch.object(forecast.requests, 'get', mock.Mock(side_effect=get))


def forecast_for(first_day, last_day):
    """The days once fetched: the first ask starts the fetch and isn't ready, the second has them."""
    assert forecast_days(*MOUNT_DIABLO, first_day, last_day) == (False, [])
    ready, days = forecast_days(*MOUNT_DIABLO, first_day, last_day)
    assert ready
    return days


@in_memory
class ForecastDaysTestCase(FetchedAtOnce, TestCase):
    def test_each_day_high_low_precip_and_wind_in_the_format_asked_for_else_the_deprecated_one(self):
        # The service answers with units; or ignores the flags; or fails only when the flags are sent.
        for service, asks in (({}, 1), ({'periods': PERIODS}, 2),
                              ({'with_units_problem': requests.HTTPError('400 Bad Request')}, 2)):
            cache.clear()
            with service_answers(**service) as get:
                days = forecast_for(date(2026, 11, 20), date(2026, 11, 22))
            forecast_asks = [call for call in get.call_args_list if call.args[0] == FORECAST_URL]
            self.assertEqual(['Feature-Flags' in call.kwargs['headers'] for call in forecast_asks],
                             [True, False][:asks], service)
            self.assertEqual(days, [
                {'date': '2026-11-20', 'label': 'Fri\xa020', 'high': 41, 'high_band': None, 'high_note': None,
                 'low': 35, 'low_band': 'cold', 'low_note': 'Cold: hypothermia possible, more so when wet',
                 'precip': 78, 'wind_mph': '7', 'wind_direction': 'NW', 'summary': 'Light Rain then Partly Sunny',
                 'symbol': RAIN},
                {'date': '2026-11-21', 'label': 'Sat\xa021', 'high': 41, 'high_band': None, 'high_note': None,
                 'low': 33, 'low_band': 'cold', 'low_note': 'Cold: hypothermia possible, more so when wet',
                 'precip': 64, 'wind_mph': '5\u201310', 'wind_direction': 'ESE', 'summary': 'Light Rain Likely',
                 'symbol': RAIN},
                {'date': '2026-11-22', 'label': 'Sun\xa022', 'high': 50, 'high_band': None, 'high_note': None,
                 'low': None, 'low_band': None, 'low_note': None,
                 'precip': 0, 'wind_mph': '10', 'wind_direction': 'N', 'summary': 'Sunny', 'symbol': '\u2600\ufe0f'},
            ])

    def test_only_the_events_days(self):
        with service_answers():
            self.assertEqual([d['date'] for d in forecast_for(date(2026, 11, 21), date(2026, 11, 21))], ['2026-11-21'])
            self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 12, 1), date(2026, 12, 3)), (True, []))

    def test_an_overnight_period_is_the_night_before(self):
        with service_answers():
            self.assertEqual(forecast_for(date(2026, 11, 19), date(2026, 11, 19)), [
                {'date': '2026-11-19', 'label': 'Thu\xa019', 'high': None, 'high_band': None, 'high_note': None,
                 'low': 34, 'low_band': 'cold', 'low_note': 'Cold: hypothermia possible, more so when wet',
                 'precip': 69, 'wind_mph': '6', 'wind_direction': 'WSW', 'summary': 'Light Rain Likely',
                 'symbol': RAIN}])

    def test_temperature_bands_from_the_heat_index_categories_and_cold_guidance(self):
        for degrees, band in ((125, 'danger'), (103, 'danger'), (102, 'extreme-caution'), (90, 'extreme-caution'),
                              (89, 'caution'), (80, 'caution'), (79, None), (41, None), (40, 'cold'),
                              (33, 'cold'), (32, 'freezing'), (-10, 'freezing'), (None, None)):
            self.assertEqual(temperature_band(degrees)[0], band, degrees)

    def test_the_symbol_is_the_most_serious_weather_the_summary_names(self):
        # Short forecasts as the service writes them.
        for summary, symbol in (
                ('Chance Showers And Thunderstorms', '\u26c8\ufe0f'), ('Slight Chance T-storms then Sunny', '\u26c8\ufe0f'),
                ('Rain And Snow Likely', SNOW), ('Freezing Rain And Snow', SNOW), ('Rain And Sleet', SNOW), ('Chance Ice Pellets', SNOW),
                ('Freezing Rain', RAIN), ('Freezing Drizzle', RAIN), ('Patchy Freezing Drizzle then Cloudy', RAIN),
                ('Patchy Freezing Fog', FOG), ('Areas Of Ice Fog', FOG), ('Freezing Fog then Sunny', FOG),
                ('Chance Light Rain then Mostly Sunny', RAIN), ('Areas Of Frost then Light Rain Likely', RAIN),
                ('Rain Showers', RAIN), ('Patchy Drizzle', RAIN),
                ('Patchy Fog then Sunny', '\U0001f32b\ufe0f'), ('Widespread Haze', '\U0001f32b\ufe0f'),
                ('Areas Of Smoke', '\U0001f32b\ufe0f'), ('Breezy', '\U0001f4a8'), ('Sunny and Windy', '\U0001f4a8'),
                ('Mostly Cloudy', '\U0001f325\ufe0f'), ('Areas Of Frost then Partly Sunny', '\u26c5'),
                ('Partly Cloudy', '\u26c5'), ('Cloudy', '\u2601\ufe0f'), ('Mostly Sunny', '\U0001f324\ufe0f'),
                ('Sunny', '\u2600\ufe0f'), ('Mostly Clear', '\U0001f319'), ('Clear', '\U0001f319'),
                ('Areas Of Frost', '\U0001f319'), ('Patchy Frost then Sunny', '\u2600\ufe0f'),
                ('', None), (None, None)):
            self.assertEqual(weather_symbol(summary), symbol, summary)

    def test_wind_in_whole_mph_without_its_unit(self):
        for speed, mph in (({'unitCode': 'wmoUnit:km_h-1', 'value': 11.112}, '7'),
                           ({'unitCode': 'wmoUnit:km_h-1', 'minValue': 1.852, 'maxValue': 7.408}, '1\u20135'),
                           ({'unitCode': 'wmoUnit:km_h-1', 'minValue': 8.0, 'maxValue': 8.1}, '5'),
                           ({'unitCode': 'wmoUnit:m_s-1', 'value': 4.47}, '10'),
                           ({'unitCode': 'wmoUnit:kt', 'value': 10}, '12')):
            self.assertEqual(wind_mph_with_unit(speed), mph, speed)
        for speed, mph in (('5 mph', '5'), ('5 to 10 mph', '5\u201310'), ('0 mph', '0'), ('10 km/h', '10 km/h')):
            self.assertEqual(wind_mph_from_text(speed), mph, speed)

    def test_temperature_in_whole_fahrenheit(self):
        for temperature, degrees in (({'unitCode': 'wmoUnit:degC', 'value': 5}, 41),
                                     ({'unitCode': 'wmoUnit:degC', 'value': 1.6666666666666667}, 35),
                                     ({'unitCode': 'wmoUnit:degC', 'value': -40}, -40),
                                     ({'unitCode': 'wmoUnit:degF', 'value': 41}, 41),
                                     ({'unitCode': 'wmoUnit:degC', 'value': None}, None)):
            self.assertEqual(fahrenheit_with_unit(temperature), degrees, temperature)
        self.assertEqual((fahrenheit(41, 'F'), fahrenheit(5, 'C')), (41, 41))

    def test_asks_in_the_new_format_with_the_sites_name_and_keeps_the_answer(self):
        with service_answers() as get:
            forecast_for(date(2026, 11, 20), date(2026, 11, 20))
            forecast_days(*MOUNT_DIABLO, date(2026, 11, 21), date(2026, 11, 21))
        self.assertEqual([c.args[0] for c in get.call_args_list],
                         ['https://api.weather.gov/points/37.8817,-121.9142', FORECAST_URL])
        self.assertEqual(get.call_args.kwargs['headers']['User-Agent'], USER_AGENT)
        self.assertEqual(get.call_args.kwargs['headers']['Feature-Flags'], FEATURE_FLAGS)

    def test_no_answer_gives_no_days_and_is_not_asked_again_at_once(self):
        for problem in (requests.Timeout(), requests.HTTPError('404 outside the US'), requests.ConnectionError()):
            cache.clear()
            with service_answers(problem=problem) as get:
                self.assertEqual(forecast_for(date(2026, 11, 20), date(2026, 11, 20)), [], problem)
                self.assertEqual(forecast_days(*MOUNT_DIABLO, date(2026, 11, 20), date(2026, 11, 20)), (True, []), problem)
            self.assertEqual(get.call_count, 1, problem)

    def test_a_grid_whose_forecast_fails_is_looked_up_again(self):
        moved = 'https://api.weather.gov/gridpoints/MTR/1,1/forecast'
        cache.set('forecast-grid:37.8817,-121.9142', moved, 60)

        answers = service_answers().new.side_effect

        def get(url, **kwargs):
            if url == moved:
                raise requests.HTTPError('404 Not Found')
            return answers(url, **kwargs)
        with mock.patch.object(forecast.requests, 'get', mock.Mock(side_effect=get)) as asked:
            self.assertEqual(forecast_for(date(2026, 11, 20), date(2026, 11, 20)), [])
            cache.delete('forecast:37.8817,-121.9142')       # as once RETRY_AFTER has passed
            self.assertEqual(len(forecast_for(date(2026, 11, 20), date(2026, 11, 20))), 1)
        self.assertEqual([call.args[0] for call in asked.call_args_list],
                         [moved, moved, 'https://api.weather.gov/points/37.8817,-121.9142', FORECAST_URL])

    def test_an_answer_it_cannot_read_gives_no_days_kept_briefly(self):
        unreadable = (dict(PERIODS_IN_THE_NEW_FORMAT[0], temperature={'unitCode': 'wmoUnit:K', 'value': 280}),
                      dict(PERIODS_IN_THE_NEW_FORMAT[0], windSpeed={'unitCode': 'wmoUnit:furlong_fortnight-1', 'value': 3}),
                      dict(PERIODS_IN_THE_NEW_FORMAT[0], startTime='Friday'),
                      {key: value for key, value in PERIODS_IN_THE_NEW_FORMAT[0].items() if key != 'windSpeed'},
                      dict(PERIODS_IN_THE_NEW_FORMAT[0], windSpeed=None))
        for period in unreadable:
            cache.clear()
            with service_answers([period]), self.assertLogs('main.lib.lookups', 'INFO'), \
                    mock.patch.object(cache, 'add', wraps=cache.add) as kept:
                self.assertEqual(forecast_for(date(2026, 11, 20), date(2026, 11, 20)), [], period)
            self.assertEqual(kept.call_args.args[1:], ({'value': None}, RETRY_AFTER), period)


@in_memory
class EventForecastPageTestCase(FetchedAtOnce, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T'))

    def event(self, first_day, days=1, point=MOUNT_DIABLO):
        start = timezone.make_aware(datetime(first_day.year, first_day.month, first_day.day, 9))
        return Event.objects.create(type='training', title='Snow camp', location='Mount Diablo', start_at=start,
                                    finish_at=start + timedelta(days=days - 1, hours=8),
                                    lat=point and str(point[0]), lon=point and str(point[1]))

    def test_the_forecast_for_the_day_before_and_each_day_of_the_event(self):
        event = self.event(date(2026, 11, 21), days=2)
        with service_answers():
            self.assertEqual(self.client.get('/event/{}/forecast/'.format(event.id)).json(), {'ready': False, 'html': ''})
            answer = self.client.get('/event/{}/forecast/'.format(event.id)).json()
        self.assertTrue(answer['ready'])
        self.assertEqual(re.findall(r'<tr class="forecast-day">\s*<td>(.*?)</td>', answer['html']),
                         ['Day before', 'OP1 Sat\xa021', 'OP2 Sun\xa022'])
        # Saturday's row: its symbol with the summary, the high unshaded, the low shaded as cold, and the rest.
        self.assertInHTML(
            '<tr class="forecast-day"><td>OP1 Sat\xa021</td>'
            '<td><span role="img" aria-label="Light Rain Likely" title="Light Rain Likely">{}</span></td>'
            '<td class="number"><span>41°</span></td>'
            '<td class="number"><span class="shade-cold" title="Cold: hypothermia possible, more so when wet">33°</span></td>'
            '<td class="number">64%</td><td class="wind"><span>5\u201310</span> <span>ESE</span></td>'
            '<td class="forecast-summary-column">Light Rain Likely</td></tr>'.format(RAIN),
            '<table>{}</table>'.format(answer['html']))
        self.assertInHTML('<tr class="forecast-note" hidden><td colspan="6">Light Rain Likely</td></tr>',
                          '<table>{}</table>'.format(answer['html']))
        # Sunday has a high and, with its night beyond the forecast, an empty low.
        self.assertInHTML('<td class="number"><span>50°</span></td><td class="number"></td>',
                          '<table>{}</table>'.format(answer['html']))

    def test_a_shaded_temperature_shows_its_band_and_why(self):
        day = {'name': 'OP1 Sat\xa021', 'symbol': '\u2600\ufe0f', 'summary': 'Sunny and Hot', 'precip': 0,
               'wind_mph': '5', 'wind_direction': 'W', 'high': 104, 'low': 31}
        for end in ('high', 'low'):
            day[end + '_band'], day[end + '_note'] = temperature_band(day[end])
        rows = '<table>{}</table>'.format(render_to_string('event_forecast.html', {'days': [day]}))
        self.assertInHTML('<td class="number"><span class="shade-danger" title="{}">104°</span></td>'.format(
            day['high_note']), rows)
        self.assertInHTML('<td class="number"><span class="shade-freezing" title="{}">31°</span></td>'.format(
            day['low_note']), rows)

    def test_no_forecast_without_a_whole_point(self):
        event = self.event(date(2026, 11, 20), point=None)
        with service_answers() as get:
            self.assertEqual(self.client.get('/event/{}/forecast/'.format(event.id)).json(), {'ready': True, 'html': ''})
        get.assert_not_called()

    def test_the_forecast_needs_a_signed_in_member(self):
        event = self.event(date(2026, 11, 20))
        self.client.logout()
        with service_answers() as get:
            self.assertEqual(self.client.get('/event/{}/forecast/'.format(event.id)).status_code, 302)
        get.assert_not_called()

    def test_the_page_asks_only_for_an_event_within_the_forecast(self):
        today = timezone.localdate()
        # An event a week away still asks: its day before is the forecast's last day.
        for first_day, days, asks in ((today + timedelta(days=2), 1, True), (today - timedelta(days=3), 5, True),
                                      (today + timedelta(days=7), 1, True), (today + timedelta(days=8), 1, False),
                                      (today - timedelta(days=1), 1, False), (today - timedelta(days=10), 1, False)):
            event = self.event(first_day, days)
            response = self.client.get('/event/{}/'.format(event.id))
            self.assertContains(response, 'NOAA Forecast</a>')
            check = self.assertContains if asks else self.assertNotContains
            check(response, '<table id="event-forecast" class="event-forecast" hidden></table>', msg_prefix=str(first_day))
            check(response, "whenReady('/event/{}/forecast/'".format(event.id), msg_prefix=str(first_day))
