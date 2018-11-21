#
#           Event Model
#
from django.db import models

from datetime import datetime, timezone

from .base import BaseModel, BasePositionModel
from .member import Member, Role

def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)

class Event(BaseModel):
    TYPES = (
        ('meeting', 'Meeting'),
        ('operation', 'Operation'),
        ('training', 'Training'),
        ('community', 'Community'))
    type = models.CharField(choices=TYPES, max_length=255)
    title = models.CharField(max_length=255)
    leaders = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=255)
    lat = models.CharField(max_length=255, blank=True, null=True)
    lon = models.CharField(max_length=255, blank=True, null=True)
    start_on = models.DateTimeField()
    finish_on = models.DateTimeField(blank=True, null=True)
    all_day = models.BooleanField(
        default=False,
        help_text='All Day events do not have a start or end time.')
    published = models.BooleanField(
        default=False,
        help_text='Published events are viewable by the public.')

    def save(self, *args, **kwargs):
        super(Event, self).save(*args, **kwargs)
        self.add_period(True)

    def __str__(self):
        return self.title

    def add_period(self, only_if_empty=False):
        q = self.period_set.all().aggregate(models.Max('position'))
        current = q['position__max']
        if current:
            next = current + 1
            if not only_if_empty:
                self.period_set.create(position=next)
        else:
            self.period_set.create()

    @models.permalink
    def get_absolute_url(self):
        return ('event_detail', [str(self.id)])


class Period(BasePositionModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    start_on = models.DateTimeField(blank=True, null=True)
    finish_on = models.DateTimeField(blank=True, null=True)
    def __str__(self):
        return "{} OP{}".format(self.event.title, self.position)

    def members_for_left_page(self):
        return Member.objects.filter(
            participant__period=self.id,
            participant__en_route_at__isnull=True)

    def members_for_returned_page(self):
        return Member.objects.filter(
            participant__period=self.id,
            participant__return_home_at__isnull=True)


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

