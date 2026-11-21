"""The county an event's point is in, and the counties within the site setting's miles of it, from USGS's
county layer in The National Map, a copy of the Census Bureau's county lines and the faster of the two;
when it gives no answer, from the Census Bureau's own TIGERweb service. Asked for in the background and
kept (main.lib.lookups)."""
import logging
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait

import requests
from dynamic_preferences.registries import global_preferences_registry

from main.lib import lookups

# Each service's county layer, the first asked first: its query URL, and the fields holding the county's name
# and its state's FIPS code, as its replies name them (USGS's in lower case).
SERVICES = (
    ('https://carto.nationalmap.gov/arcgis/rest/services/govunits/MapServer/23/query',
     'county_name', 'state_fipscode'),
    ('https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/82/query',
     'BASENAME', 'STATE'),
)
KEPT = 30 * 24 * 3600               # seconds an answer is kept
RETRY_AFTER = 10 * 60               # seconds before asking again when neither service gave an answer
STATES = dict(pair.split(':') for pair in (
    '01:AL 02:AK 04:AZ 05:AR 06:CA 08:CO 09:CT 10:DE 11:DC 12:FL 13:GA 15:HI 16:ID 17:IL 18:IN 19:IA 20:KS '
    '21:KY 22:LA 23:ME 24:MD 25:MA 26:MI 27:MN 28:MS 29:MO 30:MT 31:NE 32:NV 33:NH 34:NJ 35:NM 36:NY 37:NC '
    '38:ND 39:OH 40:OK 41:OR 42:PA 44:RI 45:SC 46:SD 47:TN 48:TX 49:UT 50:VT 51:VA 53:WA 54:WV 55:WI 56:WY '
    '60:AS 66:GU 69:MP 72:PR 78:VI').split())

logger = logging.getLogger(__name__)


def county_text(lat, lon):
    """(ready, text): the county the point is in, and any within the site setting's miles of it (text_for);
    None for a point in no county, offshore or beyond the US. Not ready while it is being asked in the
    background."""
    miles = global_preferences_registry.manager()['general__event_county_border_miles']
    return lookups.answer('county:{}:{}:{}'.format(lat, lon, miles), lambda: ask_counties(lat, lon, miles),
                          KEPT, RETRY_AFTER)


def ask_counties(lat, lon, miles):
    """The text for the point, from the first service that answers. Its two questions, the county the
    point is in and those near it, are asked at once; when either fails, the next service is asked without
    waiting for the other. With the setting at 0 miles the one question answers both."""
    for url, name_field, state_field in SERVICES:
        both = ThreadPoolExecutor(2)
        try:
            asked = [both.submit(counties, url, name_field, state_field, lat, lon, within)
                     for within in ((0, miles) if miles else (0,))]
            answered, _ = wait(asked, return_when=FIRST_EXCEPTION)
            for question in answered:
                question.result()           # raises what a failed question raised
            return text_for(asked[0].result(), asked[-1].result())
        except (requests.RequestException, ValueError, KeyError, TypeError) as problem:
            logger.info('No counties from %s for %s, %s: %s', url, lat, lon, problem)
            last_problem = problem
        finally:
            both.shutdown(wait=False)
    raise last_problem


def counties(url, name_field, state_field, lat, lon, miles):
    """(name, state) of each county the point is in, or within `miles` of it."""
    params = {'geometry': '{},{}'.format(lon, lat), 'geometryType': 'esriGeometryPoint', 'inSR': 4326,
              'spatialRel': 'esriSpatialRelIntersects', 'outFields': name_field + ',' + state_field,
              'returnGeometry': 'false', 'f': 'json'}
    if miles:
        params = dict(params, distance=miles, units='esriSRUnit_StatuteMile')
    response = requests.get(url, params=params, timeout=lookups.TIMEOUT)
    response.raise_for_status()
    # A refused query comes back as {"error": ...} with no features, which raises KeyError here.
    return [(county['attributes'][name_field], STATES.get(county['attributes'][state_field], county['attributes'][state_field]))
            for county in response.json()['features']]


def names_text(names):
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def text_for(inside, near):
    """'Contra Costa'; near a county line, 'Placer, bordering Nevada'; with counties in another state near,
    'Placer, bordering El Dorado, Carson City (NV) and Douglas (NV)': its own state's in name order, then
    other states' by state. None in no county."""
    if not inside:
        return None
    name, state = inside[0]
    others = sorted(set(near) - {inside[0]}, key=lambda county: (county[1] != state, county[1], county[0]))
    if not others:
        return name
    return '{}, bordering {}'.format(name, names_text(
        [other if other_state == state else '{} ({})'.format(other, other_state) for other, other_state in others]))
