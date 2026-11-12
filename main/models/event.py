#
#           Event Model
#
from django.db import models
from django.urls import reverse

from datetime import datetime, timezone, timedelta
from simple_history.models import HistoricalRecords

from .base import BaseModel, BasePositionModel
from .documents import Aar, AhcLog, LogisticsSpreadsheet
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
    description_private = models.TextField(
        blank=True, null=True, verbose_name='Additional private description',
        help_text='This text will be added to the description text above.')
    location = models.CharField(max_length=255)
    location_private = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='Private version of location',
        help_text='Replaces location field on internal calendar.')
    lat = models.CharField(max_length=255, blank=True, null=True)
    lon = models.CharField(max_length=255, blank=True, null=True)
    start_at = models.DateTimeField()
    finish_at = models.DateTimeField()
    all_day = models.BooleanField(
        default=False,
        help_text='All Day events do not have a start or end time.')
    published = models.BooleanField(
        default=False,
        help_text='Published events are viewable on the public and private calendar.')
    gcal_id = models.CharField(max_length=255, blank=True, null=True)  # deprecated: we are switching to gcal event IDs derived from our own event IDs
    gcal_id_private = models.CharField(max_length=255, blank=True, null=True)  # deprecated: we are switching to gcal event IDs derived from our own event IDs
    history = HistoricalRecords()

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

    def get_absolute_url(self):
        return reverse('event_detail', args=[str(self.id)])

    def members(self):
        return Member.objects.filter( participant__period__event=self.id )

    def create_aar(self):
        if not hasattr(self, 'aar'):
            aar = Aar(event=self)
            aar.save()
            aar.add_writers(self.members())
        return self.aar

    def create_ahc_log(self):
        if not hasattr(self, 'ahc_log'):
            ahc_log = AhcLog(event=self)
            ahc_log.save()
            ahc_log.add_writers(self.members())
        return self.ahc_log

    def create_logistics_spreadsheet(self):
        if not hasattr(self, 'logistics_spreadsheet'):
            logistics_spreadsheet = LogisticsSpreadsheet(event=self)
            logistics_spreadsheet.save()
        return self.logistics_spreadsheet


class PeriodManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('event')

class Period(BasePositionModel):
    objects = PeriodManager()

    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    start_at = models.DateTimeField(blank=True, null=True)
    finish_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

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

    def prefetched_members_for_info_page(self):
        # used in event_detail
        # Ideally we'd do a Member query directly, or a select_related() or
        # prefetch_related() on the participant_set. But, when
        # participant_set__member has already been prefetched, that actually
        # makes things worse, triggering a new query per period when all the
        # relevant objects are already loaded! Possibly we could inspect
        # self._fields_cache to figure out whether we need to do more
        # prefetching... but currently this is only used in one place, so
        # just make the name explicit for now.
        return [p.member for p in self.participant_set.all()]


class Participant(BaseModel):
    period = models.ForeignKey(Period, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    ahc = models.BooleanField(default=False)
    ol = models.BooleanField(default=False)
    logistics = models.BooleanField(default=False)
    comment = models.CharField(max_length=255, blank=True, null=True)
    en_route_at = models.DateTimeField(blank=True, null=True)
    return_home_at = models.DateTimeField(blank=True, null=True)
    signed_in_at = models.DateTimeField(blank=True, null=True)
    signed_out_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords()

    def __str__(self):
        return "{} ({})".format(self.member, self.period)

    @property
    def timedelta(self):
        if self.en_route_at is not None and self.return_home_at is not None:
            return self.return_home_at - self.en_route_at
        if self.signed_in_at is not None and self.signed_out_at is not None:
            return self.signed_out_at - self.signed_in_at
        return timedelta()

    @property
    def hours(self):
        return self.timedelta.total_seconds() / 3600
