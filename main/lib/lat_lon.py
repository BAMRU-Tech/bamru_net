"""A point as a member types or pastes it into an event's Lat/Lon box, in any common form, read
as decimal latitude and longitude on WGS84 (which NAD83 matches to within a metre or two).

The forms read:
- decimal degrees: 37.7456, -119.5936 · 37.7456 N 119.5936 W · N37.7456 W119.5936
- degrees and decimal minutes, as GPS units show them: N 37° 44.736' W 119° 35.616'
- degrees, minutes and seconds, as Google Maps shows them: 37°44'44.2"N 119°35'37.0"W
- UTM: 11S 271485 4180757 · 11 271485mE 4180757mN
- USNG, which is MGRS for the US: 11S KB 71484 80756 · 11SKB7148480756
"""
import re
import warnings
from collections import namedtuple

import mgrs
import utm
from dynamic_preferences.registries import global_preferences_registry

Point = namedtuple('Point', 'lat lon form')
# Longer than any point written out, such as Latitude: N 37° 44' 44.2" Longitude: W 119° 35' 37.0".
LONGEST = 100


class NotAPoint(ValueError):
    """Text that can't be read as a point; the message says why, for the member."""


def degrees_text(degrees):
    """Degrees as stored and shown: up to six decimal places, about 10 cm."""
    return '{:.6f}'.format(degrees).rstrip('0').rstrip('.')


def point_text(lat, lon):
    return '{}, {}'.format(degrees_text(lat), degrees_text(lon))


def read_point(text):
    """The point the text gives, or None for an empty box; NotAPoint when it can't be read."""
    text = ' '.join((text or '').split())           # one space between words, however it was pasted
    if not text:
        return None
    if len(text) > LONGEST:
        raise NotAPoint(UNREADABLE)
    text = text.translate(TYPOGRAPHY).replace("''", '"').upper()
    for pattern, read in ((USNG, usng_point), (UTM, utm_point)):
        found = pattern.fullmatch(text)
        if found:
            return read(*found.groups())
    return degrees_point(text)


def reading_note(point):
    """What the box did to the member's text, for the note under it; empty when nothing changed."""
    return '' if point.form == 'decimal degrees' else 'Converted from {}.'.format(point.form)


# ---- UTM and USNG ------------------------------------------------------------------------------

BANDS = 'CDEFGHJKLMNPQRSTUVWX'                  # 8° latitude bands from 80°S; N and after are north
UTM = re.compile(r'(?:UTM:?\s*)?(?:ZONE\s*)?(\d{1,2})\s*([C-HJ-NP-X])?\s+0?(\d{6}(?:\.\d+)?)\s*(?:M?\s*E)?\s*[,;]?\s*'
                 r'(\d{7}(?:\.\d+)?)\s*(?:M?\s*N)?')
USNG = re.compile(r'(?:(?:USNG|MGRS):?\s*)?(\d{1,2})\s*([C-HJ-NP-X])\s*([A-HJ-NP-Z])\s*([A-HJ-NP-V])\s*'
                  r'(\d+(?:\s+\d+)?)')


def utm_point(zone, band, easting, northing):
    zone = utm_zone(zone)
    # strict=False: an easting or northing off the grid is refused below, in this module's words.
    lat, lon = utm.to_latlon(float(easting), float(northing), zone, northern=not band or band >= 'N', strict=False)
    point = checked(lat, lon, 'UTM')
    # A zone is 6° wide; half a degree more allows a point read just across its edge.
    if abs((lon - (6 * zone - 183) + 180) % 360 - 180) > 3.5:
        raise NotAPoint('Easting {} is outside zone {}. Check the zone and the easting.'.format(easting, zone))
    # N is also how GIS tools write the northern hemisphere, as in "UTM zone 11N".
    if band and band != 'N' and not in_band(band, lat):
        raise NotAPoint('This point is not in latitude band {}. Check the band letter and the northing.'.format(band))
    return point


def in_band(band, lat):
    """Whether the latitude is in the band, give or take half a degree."""
    edge = -80 + 8 * BANDS.index(band)
    return edge - 0.5 <= lat <= edge + (12 if band == 'X' else 8) + 0.5


def usng_point(zone, band, column, row, digits):
    zone = utm_zone(zone)
    parts = digits.split()
    if len(parts) == 1 and len(digits) % 2 == 0:
        parts = [digits[:len(digits) // 2], digits[len(digits) // 2:]]
    if len(parts) != 2 or len(parts[0]) != len(parts[1]) or len(parts[0]) > 5:
        raise NotAPoint('A USNG point needs as many easting digits as northing digits, '
                        'such as 11S KB 71484 80756.')
    no_such_square = NotAPoint('Zone {} has no 100 km square {}{} in latitude band {}. Check its letters.'.format(
        zone, column, row, band))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)     # of a square at the edge of its band, checked below
            _, hemisphere, easting, northing = mgrs.MGRS().MGRSToUTM(
                '{}{}{}{}{:0<5}{:0<5}'.format(zone, band, column, row, *parts))
    except mgrs.core.MGRSError:
        raise no_such_square
    # mgrs gives the middle of the 1 m square; USNG names its south-west corner, as UTM's digits do.
    lat, lon = utm.to_latlon(easting - 0.5, northing - 0.5, zone, northern=hemisphere == 'N', strict=False)
    if not in_band(band, lat):
        raise no_such_square
    return checked(lat, lon, 'USNG')


def utm_zone(zone):
    if not 1 <= int(zone) <= 60:
        raise NotAPoint('UTM zones run from 1 to 60.')
    return int(zone)


# ---- degrees -----------------------------------------------------------------------------------

TYPOGRAPHY = str.maketrans({'º': '°', '˚': '°', '′': "'", '’': "'", '‘': "'", '´': "'", '`': "'",
                            '″': '"', '“': '"', '”': '"', '−': '-', '–': '-',
                            '\u200b': None, '\u200e': None, '\ufeff': None})
LONGITUDE_FIRST = re.compile(r'\b(?:LONGITUDE|LONG|LON|LNG)\b.*\bLAT')
LABELS = re.compile(r'\b(?:LATITUDE|LONGITUDE|LAT|LONG|LON|LNG)\b\s*[:=]?|\b(?:DEGREES|DEG)\b')
TOKENS = re.compile(r'([NSEW])|([-+]?\d+(?:\.\d+)?)\s*([°\'"])?|([,;/])|(\S)')
FORMS = ('decimal degrees', 'degrees and minutes', 'degrees, minutes and seconds')
PLACES = {"'": 1, '"': 2}                       # minutes and seconds, by their marks
ORDER = 'Write degrees, then minutes, then seconds, such as 37°44\'44.2"N.'
# One point, Yosemite Valley, in each form the box reads, for when a member's text can't be read.
EXAMPLES = ('37.7456, -119.5936', "N 37° 44.736' W 119° 35.616'", '37°44\'44.2"N 119°35\'37.0"W',
            'UTM 11S 271485 4180757', 'USNG 11S KB 71484 80756')
UNREADABLE = 'Enter a point in any of these forms: {}; {}; {}; {}; or {}.'.format(*EXAMPLES)


def degrees_point(text):
    if LONGITUDE_FIRST.search(text):
        raise NotAPoint('Latitude comes first.')
    parts = degree_parts(LABELS.sub(' ', text))
    if len(parts) != 2 or not all(numbers for numbers, _ in parts):
        raise NotAPoint(UNREADABLE)
    values, places = zip(*(part_value(numbers, letter) for numbers, letter in parts))
    values, letters = list(values), [letter for _, letter in parts]
    if letters[0] in ('E', 'W') or letters[1] in ('N', 'S'):
        values.reverse()
        letters.reverse()
    if letters[0] in ('E', 'W') or letters[1] in ('N', 'S'):
        raise NotAPoint('Give one latitude (N or S) and one longitude (E or W).')
    if any(abs(value) > 180 for value in values):
        raise NotAPoint(UNREADABLE)                 # not degrees, such as a UTM point without its zone
    return checked(values[0], values[1], FORMS[max(places)])


def degree_parts(text):
    """The text's numbers grouped into a latitude and a longitude: [(numbers, hemisphere letter)]."""
    parts, numbers, letter = [], [], None

    def close():
        nonlocal numbers, letter
        if numbers or letter:
            parts.append((numbers, letter))
        numbers, letter = [], None

    for hemisphere, number, symbol, separator, other in TOKENS.findall(text):
        if other:
            raise NotAPoint(UNREADABLE)
        if separator:
            close()
        elif hemisphere:
            if numbers and not letter:              # after its numbers: 37.7456 N
                letter = hemisphere
                close()
            else:                                   # before them: N 37.7456
                close()
                letter = hemisphere
        else:
            if numbers and starts_a_part(numbers, number, symbol):
                close()
            numbers.append((number, symbol))
    close()
    return parts


def starts_a_part(numbers, number, symbol):
    """Whether a number starts the next latitude or longitude rather than adding minutes or seconds."""
    last = numbers[-1][0]
    return len(numbers) == 3 or '.' in last or symbol == '°' or number[0] in '+-' or float(number) >= 60


def part_value(numbers, letter):
    """A latitude or longitude, and its last place (0 degrees, 1 minutes, 2 seconds). Minutes and
    seconds are placed by their marks, or else in order."""
    (degrees, symbol), value, last = numbers[0], abs(float(numbers[0][0])), 0
    if symbol not in ('', '°'):
        raise NotAPoint(ORDER)
    for number, symbol in numbers[1:]:
        place = PLACES.get(symbol, last + 1)
        if not last < place <= 2:
            raise NotAPoint(ORDER)
        value, last = value + float(number) / 60 ** place, place
    negative = degrees.startswith('-')
    if negative and letter in ('N', 'E'):
        raise NotAPoint('A minus sign and {} disagree: use one or the other.'.format(letter))
    return (-value if negative or letter in ('S', 'W') else value), last


def checked(lat, lon, form):
    """The point, if it's on the map. Degrees over 180 were refused already, so only their latitude
    can be out of range here."""
    if abs(lat) <= 90 and abs(lon) <= 180:
        return Point(lat, lon, form)
    if form in ('UTM', 'USNG'):
        raise NotAPoint('This {} point is off the map. Check its easting and northing.'.format(form))
    raise NotAPoint('Latitude comes first, and runs from -90 to 90.')


# ---- the team's usual area ---------------------------------------------------------------------

def area_edges(text):
    """The usual area's south, north, west and east edges, from the site setting's text."""
    try:
        edges = [float(edge) for edge in text.split(',')]
    except ValueError:
        edges = []
    if len(edges) != 4 or not (edges[0] < edges[1] and edges[2] < edges[3]):
        raise ValueError('Enter four numbers in this order: south, north, west and east edges, such as '
                         '32.4, 46.4, -124.8, -114.0. South must be less than north, and west less than east.')
    return edges


def area_warning(lat, lon):
    """None for a point inside the area the team usually works in, from the site setting; for a
    point outside it, a warning that asks the member to check it."""
    south, north, west, east = area_edges(global_preferences_registry.manager()['general__event_area'])
    if south <= lat <= north and west <= lon <= east:
        return None
    return 'This point is outside the area the team usually works in. Check its numbers and minus signs.'
