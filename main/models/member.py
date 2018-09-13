#
#           Member Model
#

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from .base import BaseModel, BasePositionModel

from datetime import timedelta

class CustomUserManager(BaseUserManager):
    """Allows username to be case insensitive."""
    def get_by_natural_key(self, username):
        case_insensitive_username_field = '{}__iexact'.format(self.model.USERNAME_FIELD)
        return self.get(**{case_insensitive_username_field: username})

class ActiveMemberManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(member_rank__in=['TM','FM','T'])

class CurrentMemberManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            member_rank__in=['TM','FM','T','R','S','A'])

class Member(AbstractBaseUser, PermissionsMixin, BaseModel):
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    objects = CustomUserManager()
    active = ActiveMemberManager()
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

    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    username = models.CharField(max_length=255, unique=True)
    member_rank = models.CharField(choices=TYPES, max_length=255, blank=True)
    dl = models.CharField(max_length=255, blank=True, null=True)
    ham = models.CharField(max_length=255, blank=True, null=True)
    v9 = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
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
    def rank(self):
        return self.member_rank  # Don't rename member.rank to rank, postgres gets upset


    @property
    def rank_order(self):
        """ Return int, lowest value is TM, follows order in Member.TYPES """
        for rankTuple in Member.TYPES:
            if rankTuple[0] == self.rank:
                return Member.TYPES.index(rankTuple)
        return len(Member.TYPES)

    @property
    def roles(self):
        """ Return string, list of ordered roles """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.role ] for r in roles ]
        return ', '.join([ r[1] for r in sorted(result) ])

    @property
    def role_order(self):
        """ Return int for the highest priority role """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.role ] for r in roles ]
        try:
            return [ r[0] for r in sorted(result) ][0]
        except:
            return len(Role.TYPES)


    @property
    def display_email(self): # FIXME: needs a priority
        """ Return first email """
        try:
            return self.email_set.first().address
        except:
            return ''
            
    @property
    def display_phone(self): # FIXME: needs a priority
        """ Return first phone """
        try:
            return self.phone_set.first().number
        except:
            return ''
        
    @property
    def short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def isActive(self): # FIXME: Needs a filter
        """ Return member status, True is active member """
        return self.rank in ['TM', 'FM', 'T']

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
        ('home', 'home FIXME'),
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
        return "{}, {}, {}, {} {}".format(self.address1, self.address2, self.city, self.state, self.zip)


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
        return 'TODO'

    @staticmethod
    def current_year():
        return timezone.now().year

    @staticmethod
    def current_quarter():
        return int(timezone.now().month/4)+1

    @property
    def end(self):
        return 'TODO'

    @staticmethod
    def num_weeks_in_quarter(year, quarter):
        return 13  # TODO: Calculate for 53-week years

    @classmethod
    def weeks(cls, year, quarter):
        return range(1, 1 + cls.num_weeks_in_quarter(year, quarter))


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
    def is_expired(self):
        # We will allow certs expiring today, thus < not <=
        return ((self.expiration is None) or
                (self.expiration < timezone.now().date()))

    @property
    def color(self):
        exp = self.expiration
        now = timezone.now().date()
        if not exp:
            return "white"
        if exp < now:
            return "pink"
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
