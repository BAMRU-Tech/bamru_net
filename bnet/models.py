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

from .model_base import BaseModel
from .model_member import Member, Role, Phone, Email, Address, EmergencyContact, OtherInfo
from .model_event import Event, Period, Participant


class AvailOps(models.Model):
    id = models.IntegerField(primary_key=True)  # AutoField?
    member_id = models.IntegerField(blank=True, null=True)
    start_on = models.DateField(blank=True, null=True)
    end_on = models.DateField(blank=True, null=True)
    comment = models.TextField(blank=True, null=True)  # This field type is a guess.
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)


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
