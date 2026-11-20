"""Makes counties.geojson beside this script: the Census Bureau's 2024 county outlines at 1:5,000,000
for California, Nevada and Oregon, with coordinates to 4 decimal places (about 10 m).

Source: https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_5m.zip, unzipped.
Needs pyshp (pip install pyshp), which only this script uses; the site reads the GeoJSON.
Usage: python main/data/make_counties.py PATH/TO/cb_2024_us_county_5m.shp
"""
import json
import sys
from pathlib import Path

import shapefile

STATES = {'06': 'CA', '32': 'NV', '41': 'OR'}
DECIMAL_PLACES = 4


def rounded(coordinates):
    if isinstance(coordinates[0], (int, float)):
        return [round(coordinates[0], DECIMAL_PLACES), round(coordinates[1], DECIMAL_PLACES)]
    return [rounded(part) for part in coordinates]


reader = shapefile.Reader(sys.argv[1])
fields = [field[0] for field in reader.fields[1:]]
features = []
for item in reader.iterShapeRecords():
    record = dict(zip(fields, item.record))
    if record['STATEFP'] in STATES:
        geometry = item.shape.__geo_interface__
        features.append({
            'type': 'Feature',
            'properties': {'geoid': record['GEOID'], 'name': record['NAMELSAD'], 'state': STATES[record['STATEFP']]},
            'geometry': {'type': geometry['type'], 'coordinates': rounded(geometry['coordinates'])},
        })
text = json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':'))
(Path(__file__).resolve().parent / 'counties.geojson').write_text(text)
