#
#           Member Model
#

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from .base import BaseModel, BasePositionModel

from datetime import date, datetime, timedelta

class CustomUserManager(BaseUserManager):
    """Allows username to be case insensitive."""
    def get_by_natural_key(self, username):
        case_insensitive_username_field = '{}__iexact'.format(self.model.USERNAME_FIELD)
        return self.get(**{case_insensitive_username_field: username})

class CurrentMemberManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(membership__in=Member.CURRENT_MEMBERS)

class Member(AbstractBaseUser, PermissionsMixin, BaseModel):
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    objects = CustomUserManager()
    members = CurrentMemberManager()
    
    TYPES = (
        ('TM', 'Technical Member'),
        ('FM', 'Field Member'),
        ('T', 'Trainee'),
        ('R', 'Reserve'),
        ('S', 'Support'),
        ('A', 'Associate'),
        ('G', 'Guest'),
        ('MA', 'Member Alum'),
        ('GA', 'Guest Alum'),
        ('MN', 'Member No-contact'),
        ('GN', 'Guest No-contact'),
        )

    CURRENT_MEMBERS = ('TM', 'FM', 'T', 'R', 'S', 'A') # Current member of the unit
    AVAILABLE_MEMBERS = ('TM', 'FM', 'T', 'S')         # Available for operations
    PRO_MEMBERS = ('TM', 'FM', 'T')                    # Available for pro-deals
    DO_SHIFT_MEMBERS = ('TM', 'FM', 'T')               # Notify for DO shift changes
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, unique=True)
    membership = models.CharField(choices=TYPES, max_length=255, blank=True)
    dl = models.CharField(max_length=255, blank=True, null=True)
    ham = models.CharField(max_length=255, blank=True, null=True)
    v9 = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True) # Django: Can log in
    is_staff = models.BooleanField(default=False) # Django: Can use admin site
    is_current_do = models.BooleanField(default=False)
    sign_in_count = models.IntegerField(default=0)
    last_sign_in_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        """ Returns the first_name plus the last_name, with a space in between."""
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    @property
    def status(self):
        return self.membership


    @property
    def status_order(self):
        """ Return int, lowest value is TM, follows order in Member.TYPES """
        for statusTuple in Member.TYPES:
            if statusTuple[0] == self.membership:
                return Member.TYPES.index(statusTuple)
        return len(Member.TYPES)

    @property
    def roles(self):
        """ Return string, list of ordered roles """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.role ] for r in roles ]
        return ', '.join([ r[1] for r in sorted(result) ])

    @property
    def classic_roles(self):
        """ Return string, list of ordered roles """
        roles = [r.role for r in self.role_set.all()] + [self.status]
        CLASSIC_ROSTER_TYPES = ['Bd', 'OL', 'TM', 'FM', 'T']
        result = [r for r in CLASSIC_ROSTER_TYPES if r in roles]
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
        try:
            return self.email_set.first().address
        except AttributeError:
            return ''

    @property
    def personal_email(self):
        try:
            return self.email_set.filter(type='Personal').first().address
        except AttributeError:
            return ''

    @property
    def work_email(self):
        try:
            return self.email_set.filter(type='Work').first().address
        except AttributeError:
            return ''

    @property
    def display_phone(self):
        """ Return first phone """
        try:
            return self.phone_set.first().number
        except AttributeError:
            return ''

    @property
    def mobile_phone(self):
        try:
            return self.phone_set.filter(type='Mobile').first().number
        except AttributeError:
            return ''

    @property
    def home_phone(self):
        try:
            return self.phone_set.filter(type='Home').first().number
        except AttributeError:
            return ''

    @property
    def work_phone(self):
        try:
            return self.phone_set.filter(type='Work').first().number
        except AttributeError:
            return ''

    @property
    def short_name(self):
        "Returns the short name for the user."
        return self.first_name

    @models.permalink
    def get_absolute_url(self):
        return ('member_detail', [str(self.id)])


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
        ('OL', 'Operators Leader'),
        ('WEB', 'Web Master'),
        ('REG', 'Registar'),
        ('TM', 'Active Technical Member'),
        ('FM', 'Active Field Member'),
        ('T', 'Active Trainee'),
    )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    role = models.CharField(choices=TYPES, max_length=255, blank=True)

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
    type = models.CharField(choices=TYPES, max_length=255)
    pagable = models.BooleanField(default=True)
    address = models.CharField(max_length=255)


class Phone(BasePositionModel):
    TYPES = (
        ('Home', 'Home'),
        ('Mobile', 'Mobile'),
        ('Work', 'Work'),
        ('Pager', 'Pager'),
        ('Other', 'Other'),
        )
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    type = models.CharField(choices=TYPES, max_length=255)
    number = models.CharField(max_length=255)
    pagable = models.BooleanField(default=True)
    sms_email = models.CharField(max_length=255, blank=True, null=True)


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
    available = models.BooleanField(default=False)
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

    @staticmethod
    def current_year():
        return timezone.now().year

    @staticmethod
    def current_quarter():
        return int(timezone.now().month/4)+1

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
    expiration = models.DateField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    link = models.TextField(blank=True, null=True)
    cert_file = models.TextField(blank=True, null=True)
    cert_file_name = models.TextField(blank=True, null=True)
    cert_content_type = models.TextField(blank=True, null=True)
    cert_file_size = models.TextField(blank=True, null=True)
    cert_updated_at = models.TextField(blank=True, null=True)
    ninety_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    thirty_day_notice_sent_at = models.DateTimeField(blank=True, null=True)
    expired_notice_sent_at = models.DateTimeField(blank=True, null=True)

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
        return ((self.expiration is not None) and
                (self.expiration < timezone.now().date()))

    @property
    def color(self):
        exp = self.expiration
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
