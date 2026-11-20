"""The ground elevation at a point, in feet, from the USGS Elevation Point Query Service, kept in the
server process's cache so each point is asked for once."""
import logging

import requests
from django.core.cache import cache

SERVICE = 'https://epqs.nationalmap.gov/v1/json'
TIMEOUT = 10
KEPT = 30 * 24 * 3600               # seconds an answer is kept
RETRY_AFTER = 10 * 60               # seconds before asking again when USGS gave no answer
OUTSIDE_THE_US = -1000              # USGS answers -1000000 for a point outside the US

# Light shading for an elevation in feet, in the same shades as the forecast's heat bands, from the risk of
# altitude illness for someone coming up from below 4,000 ft: at 8,000 ft and up anyone not acclimatized is
# at risk, and a first night at 9,000 to 11,150 ft is moderate risk and above 11,150 ft high risk (CDC Yellow
# Book 2026, High-Altitude Travel and Altitude Illness, Table 3.5.1). The Wilderness Medical Society names
# rescue teams working hard soon after arriving above 3,500 m (11,500 ft) as very high risk (2024 guidelines).
ALTITUDE_BANDS = (
    (11150, 'danger', 'High risk of altitude sickness sleeping here the first night, higher still working hard soon after arriving'),
    (9000, 'extreme-caution', 'Moderate risk of altitude sickness sleeping here the first night'),
    (8000, 'caution', 'Altitude sickness possible for anyone not acclimatized, more so sleeping here'),
)

logger = logging.getLogger(__name__)


def altitude_band(feet):
    """The band an elevation falls in and what it means, or (None, None)."""
    for at_least, band, note in ALTITUDE_BANDS:
        if feet is not None and feet >= at_least:
            return band, note
    return None, None


def elevation_feet(lat, lon):
    """Whole feet at the point, or None: outside the US, not on land (USGS answers 0), or no answer."""
    key = 'elevation:{}:{}'.format(lat, lon)
    kept = cache.get(key)
    if kept is not None:
        return kept['feet']
    try:
        response = requests.get(SERVICE, timeout=TIMEOUT, params={
            'x': lon, 'y': lat, 'wkid': 4326, 'units': 'Feet', 'includeDate': 'false'})
        response.raise_for_status()
        value = float(response.json()['value'])
    except (requests.RequestException, ValueError, KeyError, TypeError) as problem:
        logger.info('No elevation from USGS for %s, %s: %s', lat, lon, problem)
        cache.set(key, {'feet': None}, RETRY_AFTER)
        return None
    feet = None if value == 0 or value < OUTSIDE_THE_US else round(value)
    cache.set(key, {'feet': feet}, KEPT)
    return feet
