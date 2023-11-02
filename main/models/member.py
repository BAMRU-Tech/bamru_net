#
#           Member Model
#

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Count, Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from .base import BaseModel, BasePositionModel
from main.lib import admin, phone

from collections import defaultdict
from datetime import date, datetime, timedelta
import math
from simple_history.models import HistoricalRecords

import logging
logger = logging.getLogger(__name__)


class DisplayMemberStatusTypeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            is_display=True)

class MemberStatusType(BasePositionModel):
    objects = models.Manager() 
    displayed = DisplayMemberStatusTypeManager()

    short = models.CharField(max_length=255)
    long = models.CharField(max_length=255)
    is_current = models.BooleanField(default=True) # member
    is_available = models.BooleanField(default=True) # page for callouts
    is_pro_eligible = models.BooleanField(default=True)
    is_do_eligible = models.BooleanField(default=True) # can serve DO shifts
    is_display = models.BooleanField(default=True) # show on site
    is_default = models.BooleanField(default=False) # Create new users with this type

    def __str__(self):
        return self.short


class CustomUserManager(BaseUserManager):
    """Allows username to be case insensitive."""
    def get_by_natural_key(self, username):
        case_insensitive_username_field = '{}__iexact'.format(self.model.USERNAME_FIELD)
        return self.get(**{case_insensitive_username_field: username})

class CurrentMemberManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().select_related('status').filter(
            status__is_current=True)

class Member(AbstractBaseUser, PermissionsMixin, BaseModel):
    USERNAME_FIELD = 'username'
    EMAIL_FIELD = 'display_email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    objects = CustomUserManager()
    members = CurrentMemberManager()
    
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, unique=True)
    profile_email = models.CharField(max_length=255, blank=True, null=True)
    status = models.ForeignKey(MemberStatusType, on_delete=models.PROTECT, null=True)
    dl = models.CharField(max_length=255, blank=True, null=True)
    ham = models.CharField(max_length=255, blank=True, null=True)
    v9 = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True) # Django: Can log in
    is_staff = models.BooleanField(default=False) # Django: Can use admin site
    is_current_do = models.BooleanField(default=False)
    sign_in_count = models.IntegerField(default=0)
    last_sign_in_at = models.DateTimeField(blank=True, null=True)
    history = HistoricalRecords(excluded_fields=[
        'password', 'last_login', 'last_sign_in_at', 'sign_in_count', 'is_current_do'])

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        """ Returns the first_name plus the last_name, with a space in between."""
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    @property
    def status_order(self):
        """ Returns value that can be used to sort by status field. """
        return self.status.position

    @property
    def roles(self):
        """ Return string, list of ordered roles """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.role ] for r in roles ]
        return ', '.join([ r[1] for r in sorted(result) ])

    @property
    def classic_roles(self):
        """ Return string, list of ordered roles combined with status"""
        roles = [r.role for r in self.role_set.all()]
        types = [r[0] for r in Role.TYPES]
        result = [r for r in types if r in roles] + [self.status.short]
        return ' '.join(result)

    @property
    def role_order(self):
        """ Return int for the highest priority role """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.role ] for r in roles ]
        if len(result) == 0:
            return len(Role.TYPES)
        return [ r[0] for r in sorted(result) ][0]

    @property
    def display_email(self):
        """ Return first email """
        if self.profile_email:
            return self.profile_email
        return self.get_email()

    @property
    def personal_email(self):
        return self.get_email('Personal')

    @property
    def work_email(self):
        return self.get_email('Work')

    @property
    def display_phone(self):
        """ Return first phone """
        return self.get_phone()

    @property
    def mobile_phone(self):
        return self.get_phone('Mobile')

    @property
    def home_phone(self):
        return self.get_phone('Home')

    @property
    def work_phone(self):
        return self.get_phone('Work')

    def get_email(self, t=None):
        try:
            return self.smart_first('email_set', self.email_set, t).address
        except (IndexError, AttributeError):
            return ''

    def get_phone(self, t=None):
        try:
            return self.smart_first('phone_set', self.phone_set, t).display_number
        except (IndexError, AttributeError):
            return ''

    def smart_first(self, name, qs, t=None):
        if name in getattr(self, '_prefetched_objects_cache', {}):
            # prefetched, just find in objects we have already
            if t is None:
                return qs.all()[0]
            else:
                # it would be nice if we cached this rather that building the
                # groups every time. But n for a single user is small.
                return self.grouped_attrs(qs)[t][0]
        # not prefetched, fall back to query
        if t is not None:
            qs = qs.filter(type=t)
        return qs.first()

    def grouped_attrs(self, related_qs):
        """related_qs must have a 'type' field (i.e. it should be email_set, phone_set, or address_set)"""
        objs = defaultdict(list)
        for o in related_qs.all():
            objs[o.type].append(o)
        return objs

    def grouped_emails(self):
        return self.grouped_attrs(self.email_set)

    def grouped_phones(self):
        return self.grouped_attrs(self.phone_set)

    def grouped_addresses(self):
        return self.grouped_attrs(self.address_set)


    @property
    def short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def do_shifts_in_past_year(self, plan_year, plan_quarter):
        """Number of DO shifts assigned to this member in the 4 quarters prior
        to the one being planned."""
        return (DoAvailable.objects.filter(
            assigned=True, member=self,
            year=plan_year - 1, quarter__gte=plan_quarter).count() +
                DoAvailable.objects.filter(
                    assigned=True, member=self,
                    year=plan_year, quarter__lt=plan_quarter).count())

    @property
    def is_unavailable(self):
        if getattr(self, '_unavailable_now', None) is not None:
            return self._unavailable_now > 0

        today = timezone.now().today().date()
        return self.unavailable_set.filter(
            start_on__lte=today, end_on__gte=today).count() > 0

    def get_absolute_url(self):
        return reverse('member_detail', args=[str(self.id)])

    def pagable_email_addresses(self):
        return [x.address for x in self.email_set.filter(pagable=True)]

    def _google_profile_info(self):
        data = {
            'name': {'givenName': self.first_name, 'familyName': self.last_name},
            'organizations': [ {'name': 'BAMRU', 'title': self.status}, ],
        }
        data['phones'] = [
            {'type': x.type.lower(), 'value': x.number}
            for x in self.phone_set.all()]
        data['emails'] = [
            {'type': x.type.lower() if x.type != 'Personal' else 'custom',
             'address': x.address}
            for x in self.email_set.all()]
        data['addresses'] = []
        for x in self.address_set.all():
            street = x.address1
            if x.address2:
                street += '\n' + x.address2
            data['addresses'].append({
                'type': x.type.lower(),
                'streetAddress': '\n'.join([x.address1, x.address2]).strip(),
                'locality': x.city,
                'region': x.state,
                'postalCode': x.zip,
                'formatted': x.multiline(),
            })
        return data

    def profile_email_to_email_set(self):
        if not self.profile_email:
            return  # Nothing to do
        email_query = self.email_set.filter(address__iexact=self.profile_email)
        if email_query:
            email = email_query.first()
            email.pagable = True
            email.type = 'Other'
            email.save()
        else:
            self.email_set.create(
                type='Other',
                pagable=True,
                address=self.profile_email)

    def update_google_profile(self):
        if self.profile_email:
            directory = admin.AdminDirectory()
            directory.update_user(self.profile_email, self._google_profile_info())

    @classmethod
    def prefetch_unavailable(cls, name='member_set'):
        return Prefetch(name, Member.annotate_unavailable(cls.objects))

    @classmethod
    def annotate_unavailable(cls, qs):
        today = timezone.now().today().date()
        return qs.annotate(
            _unavailable_now=Count('unavailable', filter=Q(unavailable__start_on__lte=today, unavailable__end_on__gte=today))
        )


class Role(BaseModel):
    TYPES = (
        ('UL', 'Unit Leader'),
        ('Bd', 'Board Member'),
        ('XO', 'Executive Officer'),
        ('OO', 'Operations Officer'),
        ('SEC', 'Secretary'),
        ('TO', 'Training Officer'),
        ('RO', 'Recruiting Officer'),
        ('TRS', 'Treasurer'),
        ('OL', 'Operation Leader'),
        ('WEB', 'Web Master'),
        ('DOS', 'DO Scheduler'),
    )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    role = models.CharField(choices=TYPES, max_length=255, blank=True)
    history = HistoricalRecords()

    @property
    def role_ordinal(self):
        """ Return int, lowest value is UL, follows order in TYPES """
        for roleTuple in Role.TYPES:
            if roleTuple[0] == self.role:
                return Role.TYPES.index(roleTuple)
        return len(Role.TYPES)


class Address(BasePositionModel):
    TYPES = (
        ('home', 'home TODO'),
        ('Home', 'Home'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255)
    address1 = models.CharField(max_length=255)
    address2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255)
    state = models.CharField(max_length=255)
    zip = models.CharField(max_length=255)

    def __str__(self):
        return self.oneline()

    def address_lines(self):
        lines = [self.address1]
        if self.address2:
            lines.append(self.address2)
        return lines

    def oneline(self):
        return "{}, {}, {} {}".format(', '.join(self.address_lines()), self.city, self.state, self.zip)

    def multiline(self):
        return "{}\n{}, {} {}".format('\n'.join(self.address_lines()), self.city, self.state, self.zip)


class Email(BasePositionModel):
    TYPES = (
        ('Home', 'Home'),
        ('Personal', 'Personal'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255, default='Personal')
    pagable = models.BooleanField(default=True)
    address = models.CharField(max_length=255)

    def __str__(self):
        return self.address


class Phone(BasePositionModel):
    TYPES = (
        ('Home', 'Home'),
        ('Mobile', 'Mobile'),
        ('Work', 'Work'),
        ('Pager', 'Pager'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255, default='Mobile')
    number = models.CharField(max_length=255, validators=[phone.validate_phone])
    pagable = models.BooleanField(default=True)
    sms_email = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        self.full_clean()
        self.number = phone.format_e164(self.number)
        return super(Phone, self).save(*args, **kwargs)

    @property
    def display_number(self):
        return phone.format_display(self.number)


class EmergencyContact(BasePositionModel):
    TYPES = (
        ('Home', 'Home'),
        ('Mobile', 'Mobile'),
        ('Work', 'Work'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    number = models.CharField(max_length=255)
    type = models.CharField(choices=TYPES, max_length=255)
    
    @property
    def display_number(self):
        return phone.format_display(self.number)


class OtherInfo(BasePositionModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)


class Unavailable(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)

    start_on = models.DateField(blank=True, null=True)
    end_on = models.DateField(blank=True, null=True)
    comment = models.CharField(max_length=255, blank=True)


class DoAvailable(BaseModel):  # was AvailDos
    """Model for Duty Officer availablilty and assignment"""
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    year = models.IntegerField()
    quarter = models.IntegerField()
    week = models.IntegerField()
    available = models.BooleanField(default=None, null=True)
    assigned = models.BooleanField(default=False)
    comment = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return '{}-{}-{} {}'.format(self.year, self.quarter, self.week,
                                    self.member)

    @property
    def start(self):
        return self.shift_start(self.year, self.quarter, self.week)

    @property
    def end(self):
        return self.shift_end(self.year, self.quarter, self.week)

    @classmethod
    def current_shift_dict(cls, date=None):
        now = timezone.now() if date is None else date
        if now.date() < DoAvailable.year_start(now.year):
            year = now.year - 1
        elif now.date() > DoAvailable.year_start(now.year + 1):
            year = now.year + 1
        else:
            year = now.year
        week1_start = cls.shift_start(year, 1, 1)
        week1_delta = now - timezone.make_aware(week1_start)
        year_week = int(math.floor(week1_delta.days / 7)) + 1 # 1 indexed
        quarter = int(math.floor((year_week - 1) / 13)) + 1  # quarter numbers start at 1
        if year_week > 39:
            quarter = 4  # Don't increment to 5 on 53 week years
        quarter_week = year_week - 13 * (quarter - 1)
        return {
            'year': year,
            'quarter': quarter,
            'week': quarter_week,
        }
    @classmethod
    def next_shift_dict(cls):
        return cls.current_shift_dict(timezone.now() + timedelta(days=7))

    @classmethod
    def current_year(cls):
        return cls.current_shift_dict()['year']

    @classmethod
    def current_quarter(cls):
        return cls.current_shift_dict()['quarter']

    @classmethod
    def current_week(cls):
        return cls.current_shift_dict()['week']

    @classmethod
    def num_weeks_in_quarter(cls, year, quarter):
        if quarter == 4 and cls.quarter_start(year, 5) != cls.quarter_start(year+1, 1):
            return 14
        return 13

    @classmethod
    def weeks(cls, year, quarter):
        return range(1, 1 + cls.num_weeks_in_quarter(year, quarter))

    @classmethod
    def year_start(cls, year):
        """Returns the first day of the first DO shift for the given year.

        Note that the year of the returned date may not be the year passed in,
        if the shift begins in December of the previous year!

        - Prior to 2014, this was the first Tuesday in January.
        - From 2014 to 2019, this is the Tuesday between Dec 25 and Dec 31.
        - Beginning in 2020, this is the Tuesday between Dec 26 and Jan 1, so
          that the first DO shift of the year always includes the day of Jan 1.
        """
        jan1 = date(year=year, month=1, day=1)
        days_after_tuesday = (jan1.weekday() - 1) % 7
        do_year_start = jan1 - timedelta(days=days_after_tuesday)
        if year < 2014 and do_year_start.day != 1:
            do_year_start += timedelta(days=7)
        if 2014 <= year and year < 2020 and do_year_start.day == 1:
            do_year_start -= timedelta(days=7)
        return do_year_start

    @classmethod
    def quarter_start(cls, year, quarter):
        return cls.year_start(year) + timedelta(days=7*13*(quarter-1))

    @classmethod
    def shift_start(cls, year, quarter, week):
        date = cls.quarter_start(year, quarter) + timedelta(days=7 * (week - 1))
        return datetime(year=date.year, month=date.month, day=date.day, hour=8)

    @classmethod
    def shift_end(cls, year, quarter, week):
        return cls.shift_start(year, quarter, week) + timedelta(days=7) - timedelta(minutes=1)

    @classmethod
    def is_transition_period(cls):
        start = cls.shift_start(**cls.next_shift_dict())
        return timezone.now() + timedelta(days=1) >= timezone.make_aware(start)

    @classmethod
    def scheduled_do(cls, year, quarter, week):
        result = cls.objects.filter(
            year=year, quarter=quarter, week=week, assigned=True)
        if result.count() != 1:
            logger.error('Expected 1 DO scheduled, got {}: {}'.format(
                result.count(), result))
            return None
        else:
            return result.first().member

    @classmethod
    def current_scheduled_do(cls):
        return cls.scheduled_do(**cls.current_shift_dict())

    @classmethod
    def next_scheduled_do(cls):
        return cls.scheduled_do(**cls.next_shift_dict())


def cert_upload_path_handler(instance, filename):
    return "certs/{id}/original/{name}".format(
        id=instance.pk, name=filename)

class Cert(BasePositionModel):
    TYPES = (
        ('medical', 'Medical'),
        ('cpr', 'CPR'),
        ('ham', 'Ham'),
        ('tracking', 'Tracking'),
        ('avalanche', 'Avalanche'),
        ('rigging', 'Rigging'),
        ('ics', 'ICS'),
        ('overhead', 'Overhead'),
        ('driver', 'SO Driver'),
        ('background', 'SO Background'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255)
    expires_on = models.DateField(blank=True, null=True)
    description = models.CharField(max_length=255)
    comment = models.CharField(max_length=255, blank=True, null=True)
    link = models.CharField(max_length=255, blank=True, null=True)
    # The following 'cert_' fields all refer to the cert_file.
    cert_file = models.FileField(upload_to=cert_upload_path_handler,
                                 max_length=255, blank=True, null=True)
    cert_name = models.CharField(max_length=255, blank=True, null=True)  # original file name
    cert_content_type = models.CharField(max_length=255, blank=True, null=True)
    cert_size = models.IntegerField(blank=True, null=True)
    ninety_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    thirty_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    expired_notice_sent_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        # cleanup possible bad values from front end
        if self.link == 'None':
            self.link = None
        if self.comment == 'None':
            self.comment = None

        if self.pk is None:
            saved_file = self.cert_file
            self.cert_file = None
            super(Cert, self).save(*args, **kwargs)
            self.cert_file = saved_file
            super(Cert, self).save()
        else:
            super(Cert, self).save(*args, **kwargs)

    def __str__(self):
        if self.description is None:
            return ""
        return self.description

    @property
    def display(self):
        for t in self.TYPES:
            if t[0] == self.type:
                return t[1]

    @property
    def is_expired(self):
        # We will allow certs expiring today, thus < not <=
        return ((self.expires_on is not None) and
                (self.expires_on < timezone.now().date()))

    @property
    def color(self):
        exp = self.expires_on
        now = timezone.now().date()
        if not exp:
            return "white"
        if exp < now:
            return "red"
        if exp < now + timedelta(days=30):
            return "orange"
        if exp < now + timedelta(days=90):
            return "yellow"
        return "limegreen"

    @classmethod
    def type_order_expression(cls):
        cases = [models.When(type=cls.TYPES[i][0], then=models.Value(i))
                 for i in range(len(cls.TYPES))]
        return models.Case(
            *cases,
            default=models.Value(len(cls.TYPES)),
            output_field=models.IntegerField(),
        )
