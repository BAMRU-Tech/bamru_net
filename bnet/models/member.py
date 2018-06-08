#
#           Member Model
#

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from .base import BaseModel, BasePositionModel


class CustomUserManager(BaseUserManager):
    """Allows username to be case insensitive."""
    def get_by_natural_key(self, username):
        case_insensitive_username_field = '{}__iexact'.format(self.model.USERNAME_FIELD)
        return self.get(**{case_insensitive_username_field: username})


class Member(AbstractBaseUser, PermissionsMixin, BaseModel):
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    objects = CustomUserManager()
    
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
    typ = models.CharField(choices=TYPES, max_length=255)
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
        """ Return member rank."""
        return self.typ
    
    @property
    def rank_order(self):
        """ Return int, lowest value is TM, follows order in Member.TYPES """
        for rankTuple in Member.TYPES:
            if rankTuple[0] == self.typ:
                return Member.TYPES.index(rankTuple)
        return len(Member.TYPES)

    @property
    def roles(self):
        """ Return string, list of ordered roles """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.typ ] for r in roles ]
        return ', '.join([ r[1] for r in sorted(result) ])

    @property
    def role_order(self):
        """ Return int for the highest priority role """
        roles = self.role_set.all()
        result = [ [ r.role_ordinal, r.typ ] for r in roles ]
        try:
            return [ r[0] for r in sorted(result) ][0]
        except:
            return len(Role.TYPES)


    @property
    def default_email(self):
        """ Return first email XXX."""
        try:
            return self.email_set.first().address
        except:
            return ''
            
    @property
    def default_phone(self):
        """ Return first phone XXX."""
        try:
            return self.phone_set.first().number
        except:
            return ''
        
    @property
    def short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def isActive(self):
        """ Return member status, True is active member XXX"""
        return self.typ in ['TM', 'FM', 'T']


# UL, Bd, XO, OO, SEC, TO, TRS, REG, WEB, Bd, OL,
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
    typ = models.CharField(max_length=255)  # TODO choices

    @property
    def role_ordinal(self):
        """ Return int, lowest value is UL, follows order in TYPES """
        for roleTuple in Role.TYPES:
            if roleTuple[0] == self.typ:
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
    typ = models.CharField(choices=TYPES, max_length=255)
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
    typ = models.CharField(choices=TYPES, max_length=255)
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
    typ = models.CharField(choices=TYPES, max_length=255)
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
    typ = models.CharField(choices=TYPES, max_length=255)
    

class OtherInfo(BasePositionModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
