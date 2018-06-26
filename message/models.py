import logging
import uuid
from datetime import datetime, timedelta

import phonenumbers
from anymail.message import AnymailMessage
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django_twilio.client import twilio_client

from bnet.models import (BaseModel, BasePositionModel, Email, Member, Period,
                         Phone)

logger = logging.getLogger(__name__)


class RsvpTemplate(BasePositionModel):
    name = models.CharField(max_length=255, blank=True, null=True)
    prompt = models.CharField(max_length=255, blank=True, null=True)
    yes_prompt = models.CharField(max_length=255, blank=True, null=True)
    no_prompt = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

    def html(self, base_url):
        yn = ''.join(['<p><a href="{}?rsvp={}">{}</a></p>'
                      .format(base_url, yn, prompt)
                      for yn, prompt in
                      (('yes', self.yes_prompt), ('no', self.no_prompt))])
        return '<p>{}</p>{}'.format(self.prompt, yn)


class Message(BaseModel):
    FORMATS = (
        ('page', 'Page'),
        ('password_reset', 'Password reset'),
        ('cert_notice', 'Cert notice'),
        ('do_shift_starting', 'DO Shift Starting'),
        ('do_shift_pending', 'DO Shift Pending'),
    )
    PERIOD_FORMATS = (
        ('invite', 'invite'),
        ('info', 'info'),
        ('broadcast', 'broadcast'),
        ('leave', 'leave'),
        ('return', 'return'),
    )
    author = models.ForeignKey(Member, on_delete=models.CASCADE)
    text = models.TextField()
    format = models.CharField(choices=FORMATS, max_length=255)
    linked_rsvp = models.ForeignKey(
        'self', on_delete=models.CASCADE, blank=True, null=True)
    ancestry = models.CharField(max_length=255, blank=True, null=True)
    period = models.ForeignKey(
        Period, on_delete=models.CASCADE, blank=True, null=True)
    period_format = models.CharField(
        choices=PERIOD_FORMATS, max_length=255, blank=True, null=True)
    rsvp_template = models.ForeignKey(
        RsvpTemplate, on_delete=models.CASCADE, blank=True, null=True)

    @models.permalink
    def get_absolute_url(self):
        return ('message:message_detail', [str(self.id)])

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
    unauth_rsvp_token = models.CharField(
        max_length=255, unique=True, null=True, default=uuid.uuid4, editable=False)
    unauth_rsvp_expires_at = models.DateTimeField(blank=True, null=True)

    def send(self):
        self.unauth_rsvp_expires_at = timezone.now() + timedelta(hours=24)
        self.save()
        if self.phone:
            for p in self.member.phone_set.filter(pagable=True):
                sms, created = OutboundSms.objects.get_or_create(
                    distribution=self, phone=p)
                if created:
                    sms.send()
        if self.email:
            for e in self.member.email_set.filter(pagable=True):
                email, created = OutboundEmail.objects.get_or_create(
                    distribution=self, email=e)
                if created:
                    email.send()

    def rsvp_display(self):
        if self.rsvp:
            if self.rsvp_answer:
                return 'Yes'
            else:
                return 'No'
        else:
            return 'PENDING'


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
        try:
            message = twilio_client.messages.create(
                body=self.distribution.message.text,
                to=e164,
                from_=settings.TWILIO_SMS_FROM,
                status_callback='http://{}{}'.format(
                    settings.HOSTNAME, reverse('bnet:sms_callback')),
            )
        except Exception as e:
            self.status = str(e)
            logger.error('Twilio error: {}'.format(e))
        else:
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
        html_body = body
        if self.distribution.message.rsvp_template:
            url = 'http://{}{}'.format(settings.HOSTNAME,
                                       reverse('message:unauth_rsvp', args=[self.distribution.unauth_rsvp_token]))
            html_body = body + self.distribution.message.rsvp_template.html(
                url)
        try:
            message = AnymailMessage(
                subject="BAMRU.net page",
                body=body,
                to=[self.email.address],
                from_email=settings.MAILGUN_EMAIL_FROM,
            )
            message.attach_alternative(
                '<html>{}</html>'.format(html_body), 'text/html')
            message.send()
        except Exception as e:
            self.status = 'Anymail exception'
            self.error_message = str(e)[:255]
            logger.error('Anymail error: {}'.format(e))
        else:
            self.sid = message.anymail_status.message_id
            self.status = message.anymail_status.status
            logger.info(dir(message.anymail_status))
        self.save()
