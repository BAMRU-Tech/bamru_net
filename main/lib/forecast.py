"""Each day's forecast at a point from the National Weather Service (api.weather.gov), for the days its
seven-day forecast covers: high and low, each with its danger band, chance of precipitation and wind.
Asked for in the background and kept (main.lib.lookups): the point's forecast grid for 30 days, as the
service asks clients to check it again from time to time, and the forecast for an hour, as the service's
own replies allow."""
import logging
import math
import re
from datetime import datetime, timedelta

import requests
from django.core.cache import cache

from main.lib import lookups

POINTS = 'https://api.weather.gov/points/'
USER_AGENT = '(bamru.net event page, https://bamru.net)'     # the service asks each client to name itself
# Ask for temperature and wind as values with their units, the format the API says it will move to. When
# that gives no answer this can read, the forecast is asked for again without the flags and read in the
# deprecated format: a number in °F, and text such as "5 to 10 mph".
FEATURE_FLAGS = 'forecast_temperature_qv, forecast_wind_speed_qv'
MPH = {'km_h-1': 1 / 1.609344, 'm_s-1': 3600 / 1609.344, 'kt': 1852 / 1609.344, 'mi_h-1': 1}
DAYS_COVERED = 7
GRID_KEPT = 30 * 24 * 3600
FORECAST_KEPT = 3600
RETRY_AFTER = 10 * 60               # seconds before asking again when the service gave no answer

logger = logging.getLogger(__name__)

# Light colour bands for a forecast temperature, in °F. Hot: the National Weather Service's heat index
# categories (weather.gov/ama/heatindex), read against the air temperature, which humidity and full sun
# push higher. Cold: freezing, below which frostbite is possible, and 40°F, at and below which the CDC
# warns of hypothermia, as it does above 40°F for someone wet (cdc.gov/winter-weather/prevention).
HOT_BANDS = (
    (103, 'danger', 'Danger: heat exhaustion likely, heat stroke possible with exertion'),
    (90, 'extreme-caution', 'Extreme caution: heat stroke, cramps or exhaustion possible with exertion'),
    (80, 'caution', 'Caution: fatigue possible with exertion'),
)
COLD_BANDS = (
    (32, 'freezing', 'Freezing: frostbite possible'),
    (40, 'cold', 'Cold: hypothermia possible, more so when wet'),
)

# The symbol for a day's weather, from the words of the service's short forecast (its icon links are
# deprecated in the API), the most serious first: "Chance Light Rain then Mostly Sunny" shows rain.
SYMBOLS = (
    (r'thunder|t-storm', '\u26c8\ufe0f'),                                      # thunder cloud and rain
    (r'snow|blizzard|sleet|flurries|wintry|\bice\b(?! fog)', '\U0001f328\ufe0f'),     # cloud with snow
    (r'rain|shower|drizzle', '\U0001f327\ufe0f'),                              # cloud with rain, freezing too
    (r'fog|haze|smoke|dust|mist', '\U0001f32b\ufe0f'),                          # fog, freezing fog too
    (r'wind|breezy|blustery|gust', '\U0001f4a8'),                               # dashing away
    (r'mostly cloudy', '\U0001f325\ufe0f'),                                    # sun behind large cloud
    (r'partly cloudy|partly sunny', '\u26c5'),                                 # sun behind cloud
    (r'cloudy|overcast', '\u2601\ufe0f'),                                       # cloud
    (r'mostly sunny', '\U0001f324\ufe0f'),                                     # sun behind small cloud
    (r'sunny', '\u2600\ufe0f'),                                                 # sun
    (r'clear', '\U0001f319'),                                                  # crescent moon: clear is the night's word
)


def weather_symbol(summary):
    """The symbol for the most serious weather the summary names, or None for words it doesn't know."""
    for words, symbol in SYMBOLS:
        if re.search(words, summary or '', re.IGNORECASE):
            return symbol
    return None


def temperature_band(degrees):
    """The band a temperature falls in and what it means, or (None, None)."""
    if degrees is not None:
        for at_least, band, note in HOT_BANDS:
            if degrees >= at_least:
                return band, note
        for at_most, band, note in COLD_BANDS:
            if degrees <= at_most:
                return band, note
    return None, None


def whole(number):
    return math.floor(number + 0.5)


def fahrenheit(degrees, unit):
    """Whole °F from a number in 'F' or 'C'."""
    if degrees is None:
        return None
    return whole(degrees * 9 / 5 + 32 if unit == 'C' else degrees)


def fahrenheit_with_unit(temperature):
    """Whole °F from a value with its unit code, 'wmoUnit:degC' or 'wmoUnit:degF'."""
    return fahrenheit(temperature['value'], {'degC': 'C', 'degF': 'F'}[temperature['unitCode'].split(':')[-1]])


def wind_mph_with_unit(speed):
    """The wind in whole mph without its unit, "7" or "5–10", from a value or range with its unit code
    ('wmoUnit:km_h-1')."""
    per = MPH[speed['unitCode'].split(':')[-1]]
    if speed.get('value') is not None:
        return str(whole(speed['value'] * per))
    low, high = whole(speed['minValue'] * per), whole(speed['maxValue'] * per)
    return str(low) if low == high else '{}\u2013{}'.format(low, high)


def wind_mph_from_text(speed):
    """The same from the deprecated format's text, "7 mph" or "5 to 10 mph"."""
    return speed[:-len(' mph')].replace(' to ', '\u2013') if speed.endswith(' mph') else speed


def read_period(period, with_units):
    """One twelve-hour period of the forecast, in plain values, from the format asked for (with_units) or
    the deprecated one; one of lookups.NO_ANSWER for a period it can't read."""
    if with_units:
        temperature, wind = fahrenheit_with_unit(period['temperature']), wind_mph_with_unit(period['windSpeed'])
    else:
        temperature = fahrenheit(period['temperature'], period.get('temperatureUnit', 'F'))
        wind = wind_mph_from_text(period['windSpeed'])
    return {
        'start': datetime.fromisoformat(period['startTime']),
        'daytime': bool(period['isDaytime']),
        'temperature': temperature,
        'precip': whole((period.get('probabilityOfPrecipitation') or {}).get('value') or 0),
        'wind_mph': wind,
        'wind_direction': period['windDirection'] or '',
        'summary': period['shortForecast'] or '',
    }


def ask(url, feature_flags=None):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/geo+json'}
    if feature_flags:
        headers['Feature-Flags'] = feature_flags
    response = requests.get(url, timeout=lookups.TIMEOUT, headers=headers)
    response.raise_for_status()
    return response.json()['properties']


def fetch_periods(point):
    forecast_url = cache.get('forecast-grid:' + point)
    if forecast_url is None:
        forecast_url = ask(POINTS + point)['forecast']
        cache.set('forecast-grid:' + point, forecast_url, GRID_KEPT)
    try:
        try:
            return [read_period(period, True) for period in ask(forecast_url, FEATURE_FLAGS)['periods']]
        except lookups.NO_ANSWER as problem:
            logger.info('No forecast with units from %s, asking in the deprecated format: %s', forecast_url, problem)
            return [read_period(period, False) for period in ask(forecast_url)['periods']]
    except requests.RequestException:
        # The service may have moved the point to another grid: look its grid up again next time.
        cache.delete('forecast-grid:' + point)
        raise


def periods(lat, lon):
    """(ready, periods): the forecast's twelve-hour periods at the point, read, or None when the service
    gave no answer or one this can't read. Not ready while it is being asked in the background."""
    point = '{:.4f},{:.4f}'.format(lat, lon)
    return lookups.answer('forecast:' + point, lambda: fetch_periods(point), FORECAST_KEPT, RETRY_AFTER)


def forecast_days(lat, lon, first_day, last_day):
    """(ready, days): each day from first_day to last_day that the forecast covers, with the high of its
    daytime period (None once that has passed), the low of the night that follows, the higher of their
    chances of precipitation, and the wind in mph, its direction, the summary and its symbol from the
    daytime period, else from the night. Not ready while the forecast is being asked in the background."""
    ready, found = periods(lat, lon)
    by_day = {}
    for period in found or []:
        start = period['start']
        # A night period starting before noon, such as "Overnight", is the night of the day before.
        day = start.date() if period['daytime'] or start.hour >= 12 else start.date() - timedelta(days=1)
        by_day.setdefault(day, {})['daytime' if period['daytime'] else 'night'] = period
    days = []
    for day in sorted(d for d in by_day if first_day <= d <= last_day):
        daytime, night = by_day[day].get('daytime'), by_day[day].get('night')
        lead = daytime or night
        high = daytime['temperature'] if daytime else None
        low = night['temperature'] if night else None
        (high_band, high_note), (low_band, low_note) = temperature_band(high), temperature_band(low)
        days.append({
            'date': day.isoformat(),
            'label': '{:%a}\u00a0{}'.format(day, day.day),     # "Sat 21", kept on one line
            'high': high, 'high_band': high_band, 'high_note': high_note,
            'low': low, 'low_band': low_band, 'low_note': low_note,
            'precip': max(p['precip'] for p in (daytime, night) if p),
            'wind_mph': lead['wind_mph'], 'wind_direction': lead['wind_direction'],
            'summary': lead['summary'], 'symbol': weather_symbol(lead['summary']),
        })
    return ready, days
