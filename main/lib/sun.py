"""Sunrise, sunset and dark (the end of civil twilight) at an event's point, for a flat horizon."""
from datetime import timedelta

from astral import Observer
from astral.sun import sun
from django.utils import timezone


def sun_times(lat, lon, day):
    """The day's sunrise, sunset and dark at the point, in local time to the nearest minute, or
    None for a point that can't be read or a day the sun doesn't rise and set there."""
    try:
        times = sun(Observer(float(lat), float(lon)), day, tzinfo=timezone.get_current_timezone())
    except ValueError:
        return None
    return {name: (times[key] + timedelta(seconds=30)).replace(second=0, microsecond=0)
            for name, key in (('sunrise', 'sunrise'), ('sunset', 'sunset'), ('dark_by', 'dusk'))}
