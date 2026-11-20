"""Each day's forecast at a point from the National Weather Service (api.weather.gov), for the days its
seven-day forecast covers: high, low, chance of precipitation and wind. Kept in the server process's
cache: the point's forecast grid for 30 days, as the service asks clients to check it again from time
to time, and the forecast for an hour, as the service's own replies allow."""
import logging
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

logger = logging.getLogger(__name__)


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


def forecast_days(lat, lon, first_day, last_day):
    """Each day from first_day to last_day that the forecast covers: the high of its daytime period
    (None once that has passed), the low of the night that follows, the higher of their chances of
    precipitation, and the wind and summary of the daytime period, else of the night."""
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
        days.append({
            'date': day.isoformat(),
            'label': '{:%a %b} {}'.format(day, day.day),
            'high': daytime['temperature'] if daytime else None,
            'low': night['temperature'] if night else None,
            'precip': max((p.get('probabilityOfPrecipitation') or {}).get('value') or 0 for p in (daytime, night) if p),
            'wind': '{} {}'.format(lead['windSpeed'], lead['windDirection']).strip(),
            'summary': lead['shortForecast'],
        })
    return days
