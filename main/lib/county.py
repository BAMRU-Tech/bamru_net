"""The county an event's point is in, or the counties on each side of a nearby county line, from the
Census Bureau's county outlines for California, Nevada and Oregon (main/data/counties.geojson)."""
import json
import math
from functools import lru_cache
from pathlib import Path

from dynamic_preferences.registries import global_preferences_registry

COUNTIES_FILE = Path(__file__).resolve().parent.parent / 'data' / 'counties.geojson'
MILES_PER_DEGREE = 69.17                        # of latitude; of longitude, this times cos(latitude)


@lru_cache(maxsize=1)
def counties():
    """Each county's name, state, polygons and bounding box (west, south, east, north), read once."""
    found = []
    for feature in json.loads(COUNTIES_FILE.read_text())['features']:
        geometry = feature['geometry']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        lons = [lon for polygon in polygons for ring in polygon for lon, _ in ring]
        lats = [lat for polygon in polygons for ring in polygon for _, lat in ring]
        found.append((feature['properties']['name'], feature['properties']['state'], polygons,
                      (min(lons), min(lats), max(lons), max(lats))))
    return found


def in_ring(ring, lon, lat):
    crossings = 0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        if (lat1 > lat) != (lat2 > lat) and lon < lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1):
            crossings += 1
    return crossings % 2 == 1


def miles_to_ring(ring, lon, lat, miles_per_lon_degree):
    nearest = math.inf
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        x1, y1 = (lon1 - lon) * miles_per_lon_degree, (lat1 - lat) * MILES_PER_DEGREE
        x2, y2 = (lon2 - lon) * miles_per_lon_degree, (lat2 - lat) * MILES_PER_DEGREE
        dx, dy = x2 - x1, y2 - y1
        along = 0 if dx == dy == 0 else max(0, min(1, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy)))
        nearest = min(nearest, math.hypot(x1 + along * dx, y1 + along * dy))
    return nearest


def counties_near(lat, lon, miles):
    """(name, state) of each county within `miles` of the point: the one it is in, then by distance."""
    miles_per_lon_degree = MILES_PER_DEGREE * math.cos(math.radians(lat))
    lon_pad, lat_pad = miles / miles_per_lon_degree, miles / MILES_PER_DEGREE
    found = []
    for name, state, polygons, (west, south, east, north) in counties():
        if not (west - lon_pad <= lon <= east + lon_pad and south - lat_pad <= lat <= north + lat_pad):
            continue
        if any(in_ring(polygon[0], lon, lat) and not any(in_ring(hole, lon, lat) for hole in polygon[1:])
               for polygon in polygons):
            distance = 0
        else:
            distance = min(miles_to_ring(ring, lon, lat, miles_per_lon_degree) for polygon in polygons for ring in polygon)
        if distance <= miles:
            found.append((distance, name, state))
    return [(name, state) for _, name, state in sorted(found)]


def names_text(names):
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def county_text(lat, lon):
    """'Contra Costa'; within the site setting's miles of a county line, 'border of Placer and Nevada';
    across a state line, 'border of Placer and El Dorado, CA, and Douglas, NV'; None in no county."""
    found = counties_near(lat, lon, global_preferences_registry.manager()['general__event_county_border_miles'])
    if not found:
        return None
    by_state = {}
    for name, state in found:
        by_state.setdefault(state, []).append(name.removesuffix(' County'))
    if len(found) == 1:
        return by_state[found[0][1]][0]
    if len(by_state) == 1:
        return 'border of ' + names_text(next(iter(by_state.values())))
    groups = ['{}, {}'.format(names_text(names), state) for state, names in by_state.items()]
    return 'border of ' + ', '.join(groups[:-1]) + ', and ' + groups[-1]
