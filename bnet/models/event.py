#
#           Event Model
#
from django.db import models

from datetime import datetime, timezone

from .base import BaseModel
from .member import Member, Role

def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)

class Event(BaseModel):
    typ = models.CharField(max_length=255)  # TODO choice XXX short version M,T,C,O
    title = models.CharField(max_length=255)
    leaders = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=255)
    lat = models.CharField(max_length=255, blank=True, null=True)
    lon = models.CharField(max_length=255, blank=True, null=True)
    start = models.DateTimeField(blank=True)
    finish = models.DateTimeField(blank=True, null=True)
    all_day = models.BooleanField(default=False)
    published = models.BooleanField(default=False)

    def __str__(self):
        return self.title

    @property
    def display_title(self):
        """ Return event title, properly sized for table display """
        """ XXX database has titles with leading spaces, seems wrong """
        title = self.title
        title = (title[:50] + '..') if len(title) > 50 else title
        return title.strip()

    @property
    def display_location(self):
        """ Return event location, properly sized for table display """
        location = self.location
        location = (location[:50] + '..') if len(location) > 50 else location
        return location.strip()
    
    @property
    def display_start(self):
        if self.all_day:
            return self.start.strftime('%x')
        else:
            return utc_to_local(self.start).strftime('%x %R')

    @property
    def start_order(self):
        return self.start.timestamp()

    @models.permalink
    def get_absolute_url(self):
        return ('event_detail', [str(self.id)])


class Period(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    position = models.IntegerField(default=1)
    start = models.DateTimeField(blank=True, null=True)
    finish = models.DateTimeField(blank=True, null=True)
    def __str__(self):
        return "{} OP{}".format(self.event.title, self.position)

class Participant(BaseModel):
    period = models.ForeignKey(Period, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    ahc = models.BooleanField(default=False)
    ol = models.BooleanField(default=False)
    comment = models.CharField(max_length=255, blank=True, null=True)
    en_route_at = models.DateTimeField(blank=True, null=True)
    return_home_at = models.DateTimeField(blank=True, null=True)
    signed_in_at = models.DateTimeField(blank=True, null=True)
    signed_out_at = models.DateTimeField(blank=True, null=True)
    def __str__(self):
        return "{} ({})".format(self.member, self.period)

