# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey has `on_delete` set to the desired behavior.
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.dispatch import receiver
from django.urls import reverse
from django_twilio.client import twilio_client

#from datetime import datetime

from anymail.message import AnymailMessage
from anymail.signals import tracking
import phonenumbers
import logging
logger = logging.getLogger(__name__)

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Member(AbstractBaseUser, PermissionsMixin, BaseModel):
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    objects = BaseUserManager()
    
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
        return self.get_full_name()

    def get_full_name(self):
        """ Returns the first_name plus the last_name, with a space in between."""
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_rank(self):
        """ Return member rank."""
        return self.typ
    rank = property(get_rank)
    
    def rank_order(self):
        """ Return int, lowest value is TM, follows order in Member.TYPES """
        for rankTuple in Member.TYPES:
            if rankTuple[0] == self.typ:
                return Member.TYPES.index(rankTuple)
        return len(Member.TYPES)
    rankOrder = property(rank_order)

    def get_roles(self):
        """ Return string, list of ordered roles """
        roles = self.role_set.all()
        result = [ [ r.get_role_ordinal(), r.typ ] for r in roles ]
        return ', '.join([ r[1] for r in sorted(result) ])
    roles = property(get_roles)

    def role_order(self):
        """ Return int for the highest priority role """
        roles = self.role_set.all()
        result = [ [ r.get_role_ordinal(), r.typ ] for r in roles ]
        try:
            return [ r[0] for r in sorted(result) ][0]
        except:
            return len(Role.TYPES)
    roleOrder = property(role_order)

    def get_default_email(self):
        """ Return first email XXX."""
        try:
            return self.email_set.first().address
        except:
            return ''
    email = property(get_default_email)
            
    def get_default_phone(self):
        """ Return first phone XXX."""
        try:
            return self.phone_set.first().number
        except:
            return ''
    phone = property(get_default_phone)
        
    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def isActive(self):
        """ Return member status, True is active member XXX"""
        return self.typ in ['TM', 'FM', 'T']


class Address(BaseModel):
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
    position = models.IntegerField(default=1)

    def __str__(self):
        return "{}, {}, {}, {} {}".format(self.address1, self.address2, self.city, self.state, self.zip)

class Email(BaseModel):
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
    position = models.IntegerField(default=1)


class Phone(BaseModel):
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
    position = models.IntegerField(default=1)

class EmergencyContact(BaseModel):
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
    position = models.IntegerField(default=1)
    

"""
from bnet.models import Member, Role
m=Member.objects.get(last_name="Chang")
r=m.get_roles()
"""

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

    def get_role_ordinal(self):
        """ Return int, lowest value is UL, follows order in TYPES """
        for roleTuple in Role.TYPES:
            if roleTuple[0] == self.typ:
                return Role.TYPES.index(roleTuple)
        return len(Role.TYPES)


class OtherInfo(BaseModel):
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    position = models.IntegerField(default=1)


################## Events ###########################################

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

    def display_title(self):
        """ Return event title, properly sized for table display """
        """ XXX database has titles with leading spaces, seems wrong """
        title = self.title
        title = (title[:50] + '..') if len(title) > 50 else title
        return title.strip()
    
    displayTitle = property(display_title);

    def display_location(self):
        """ Return event location, properly sized for table display """
        location = self.location
        location = (location[:50] + '..') if len(location) > 50 else location
        return location.strip()
    
    displayLocation = property(display_location);

    def start_order(self):
        return self.start.timestamp()

    startOrder = property(start_order)

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

#####################################################################

class Message(BaseModel):
    author = models.ForeignKey(Member, on_delete=models.CASCADE)
    text = models.TextField()
    format = models.CharField(max_length=255)  #TODO choices
    linked_rsvp_id = models.IntegerField(blank=True, null=True)  # TODO: foreign key
    ancestry = models.CharField(max_length=255, blank=True, null=True)
    period = models.ForeignKey(Period, on_delete=models.CASCADE, blank = True, null=True)
    period_format = models.CharField(max_length=255, blank=True, null=True)

    def send(self):
        for d in self.distribution_set.all():
            d.send()


class Distribution(BaseModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    email = models.BooleanField(default=False)
    phone = models.BooleanField(default=False)
    read = models.BooleanField(default=False)
    bounced = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    response_seconds = models.IntegerField(blank=True, null=True)
    rsvp = models.BooleanField(default=False)
    rsvp_answer = models.NullBooleanField()
    unauth_rsvp_token = models.CharField(max_length=255, unique=True, blank=True, null=True)
    unauth_rsvp_expires_at = models.DateTimeField(blank=True, null=True)

    def send(self):
        if self.phone:
            for p in self.member.phone_set.filter(pagable=True):
                sms, created = OutboundSms.objects.get_or_create(distribution=self, phone=p)
                if created:
                    sms.send()
        if self.email:
            for e in self.member.email_set.filter(pagable=True):
                email, created = OutboundEmail.objects.get_or_create(distribution=self, email=e)
                if created:
                    email.send()

class OutboundSms(BaseModel):
    distribution = models.ForeignKey(Distribution, on_delete=models.CASCADE)
    phone = models.ForeignKey(Phone, on_delete=models.CASCADE)
    member_number = models.CharField(max_length=255, blank=True, null=True)
    sid = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=255, blank=True, null=True)
    error_code = models.IntegerField(blank=True, null=True)
    error_message = models.CharField(max_length=255, blank=True, null=True)

    def send(self):
        e164 = phonenumbers.format_number(phonenumbers.parse(self.phone.number, 'US'),
                                          phonenumbers.PhoneNumberFormat.E164)
        self.member_number = e164
        logger.info('Sending text to {}: {}'.format(self.member_number,
                                                    self.distribution.message.text))
        message = twilio_client.messages.create(
            body=self.distribution.message.text,
            to=e164,
            from_=settings.TWILIO_SMS_FROM,
            status_callback= 'http://{}{}'.format(settings.HOSTNAME, reverse('bnet:sms_callback')),
            )
        self.sid = message.sid
        self.status = message.status
        self.error_code = self.error_code
        self.error_message = message.error_message
        self.save()

class InboundSms(BaseModel):
    sid = models.CharField(max_length=255, blank=True, null=True)
    from_number = models.CharField(max_length=255, blank=True, null=True)
    to_number = models.CharField(max_length=255, blank=True, null=True)
    body = models.CharField(max_length=255, blank=True, null=True)

class OutboundEmail(BaseModel):
    distribution = models.ForeignKey(Distribution, on_delete=models.CASCADE)
    email = models.ForeignKey(Email, on_delete=models.CASCADE)
    sid = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.CharField(max_length=255, blank=True, null=True)
    delivered = models.BooleanField(default=False)
    opened = models.BooleanField(default=False)

    def send(self):
        body = self.distribution.message.text
        message = AnymailMessage(
            subject="BAMRU.net page",
            body=body,
            to=[self.email.address],
            from_email=settings.MAILGUN_EMAIL_FROM,
            )
        message.attach_alternative('<html>{}</html>'.format(body), 'text/html')
        message.send()
        self.sid = message.anymail_status.message_id
        self.status = message.anymail_status.status
        logger.info(dir(message.anymail_status))
        self.save()

@receiver(tracking)
def handle_outbound_email_tracking(sender, event, esp_name, **kwargs):
    logger.info('{}: {} ({})'.format(event.message_id, event.event_type, event.description))
    email = OutboundEmail.objects.get(sid=event.message_id)
    email.status = event.event_type
    email.error_message = event.description
    if event.event_type == 'delivered':
        email.delivered = True
    if event.event_type == 'opened':
        email.opened = True
    email.save()
