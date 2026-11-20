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

logger = logging.getLogger(__name__)


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
