"""Each day's forecast at a point from the National Weather Service (api.weather.gov), for the days its
seven-day forecast covers: high and low, each with its danger band, chance of precipitation and wind.
Kept in the server process's cache: the point's forecast grid for 30 days, as the service asks clients
to check it again from time to time, and the forecast for an hour, as the service's own replies allow."""
import logging
import re
from datetime import datetime, timedelta

import requests
from django.core.cache import cache

POINTS = 'https://api.weather.gov/points/{:.4f},{:.4f}'
USER_AGENT = '(bamru.net event page, https://bamru.net)'     # the service asks each client to name itself
TIMEOUT = 10
DAYS_COVERED = 7
GRID_KEPT = 30 * 24 * 3600
FORECAST_KEPT = 3600
RETRY_AFTER = 10 * 60               # seconds before asking again when the service gave no answer

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
    (r'snow|blizzard|sleet|freezing|flurries|wintry|\bice\b', '\U0001f328\ufe0f'),  # cloud with snow
    (r'rain|shower|drizzle', '\U0001f327\ufe0f'),                              # cloud with rain
    (r'fog|haze|smoke|dust|mist', '\U0001f32b\ufe0f'),                          # fog
    (r'wind|breezy|blustery|gust', '\U0001f4a8'),                               # dashing away
    (r'mostly cloudy', '\U0001f325\ufe0f'),                                    # sun behind large cloud
    (r'partly cloudy|partly sunny', '\u26c5'),                                 # sun behind cloud
    (r'cloudy|overcast', '\u2601\ufe0f'),                                       # cloud
    (r'mostly sunny', '\U0001f324\ufe0f'),                                     # sun behind small cloud
    (r'sunny', '\u2600\ufe0f'),                                                 # sun
    (r'clear', '\U0001f319'),                                                  # crescent moon: clear is the night's word
)

logger = logging.getLogger(__name__)


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


def ask(url):
    response = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': USER_AGENT, 'Accept': 'application/geo+json'})
    response.raise_for_status()
    return response.json()['properties']


def periods(lat, lon):
    """The forecast's twelve-hour periods at the point, or None when the service gave no answer."""
    point = '{:.4f}:{:.4f}'.format(lat, lon)
    if cache.get('forecast-none:' + point):
        return None
    try:
        forecast_url = cache.get('forecast-grid:' + point)
        if forecast_url is None:
            forecast_url = ask(POINTS.format(lat, lon))['forecast']
            cache.set('forecast-grid:' + point, forecast_url, GRID_KEPT)
        found = cache.get('forecast:' + forecast_url)
        if found is None:
            found = ask(forecast_url)['periods']
            cache.set('forecast:' + forecast_url, found, FORECAST_KEPT)
        return found
    except (requests.RequestException, ValueError, KeyError, TypeError) as problem:
        logger.info('No forecast from the National Weather Service for %s, %s: %s', lat, lon, problem)
        cache.set('forecast-none:' + point, True, RETRY_AFTER)
        return None


def wind_mph(speed):
    """The service's wind speed in mph without its unit: "5 to 10 mph" is "5–10"."""
    return speed[:-len(' mph')].replace(' to ', '\u2013') if speed.endswith(' mph') else speed


def forecast_days(lat, lon, first_day, last_day):
    """Each day from first_day to last_day that the forecast covers: the high of its daytime period
    (None once that has passed), the low of the night that follows, the higher of their chances of
    precipitation, and the wind in mph, its direction, the summary and its symbol from the daytime period,
    else from the night."""
    by_day = {}
    for period in periods(lat, lon) or []:
        start = datetime.fromisoformat(period['startTime'])
        # A night period starting before noon, such as "Overnight", is the night of the day before.
        day = start.date() if period['isDaytime'] or start.hour >= 12 else start.date() - timedelta(days=1)
        by_day.setdefault(day, {})['daytime' if period['isDaytime'] else 'night'] = period
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
            'precip': max((p.get('probabilityOfPrecipitation') or {}).get('value') or 0 for p in (daytime, night) if p),
            'wind_mph': wind_mph(lead['windSpeed']), 'wind_direction': lead['windDirection'],
            'summary': lead['shortForecast'], 'symbol': weather_symbol(lead['shortForecast']),
        })
    return days
