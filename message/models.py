import logging
import uuid
import twilio
from argparse import Namespace
from datetime import datetime, timedelta

import phonenumbers
from anymail.message import AnymailMessage
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from main.models import (BaseModel, BasePositionModel, Email, Member, Period,
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

    @property
    def text(self):
        return self.prompt


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

    @property
    def expanded_text(self):
        if self.rsvp_template:
            return '{} {}'.format(self.text, self.rsvp_template.text)
        return self.text

    def html(self, unauth_rsvp_token):
        html_body = self.text
        if self.rsvp_template:
            url = 'http://{}{}'.format(settings.HOSTNAME,
                                       reverse('message:unauth_rsvp',
                                               args=[unauth_rsvp_token]))
            html_body += self.rsvp_template.html(url)
        return html_body

    def queue(self):
        """
        Queues the message for sending.
        Because sending can take some time, we only create the OutgoingMessages.
        Actual sending is done in the message_send task.
        """
        for d in self.distribution_set.all():
            d.queue()

    # TODO: Do not repage unavailable on invite
    def repage(self, author=None):
        from .tasks import message_send  # Here to avoid circular dependency
        old_id = self.pk
        if self.rsvp_template is None:
            logger.error('Error: trying to repage a non-rsvp message.')
        dist = self.distribution_set.filter(rsvp=False)
        message = self
        message.pk = None
        message.text = 'Repage: ' + message.text
        if author:
            message.author = author
        message.linked_rsvp_id = old_id
        if message.ancestry:
            message.ancestry = '{}, {}'.format(message.ancestry, old_id)
        else:
            message.ancestry = str(old_id)
        message.save()
        for d in dist:
            message.distribution_set.create(
                member_id=d.member.id,
                email=d.email,
                phone=d.phone)
        logger.info('Repaging {} as {}'.format(old_id, message.pk))
        message.queue()
        message_send.delay(message.pk)
        return message


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

    @property
    def text(self):
        return self.message.expanded_text

    @property
    def html(self):
        return self.message.html(self.unauth_rsvp_token)

    def queue(self):
        self.unauth_rsvp_expires_at = timezone.now() + timedelta(hours=24)
        self.save()
        if self.phone:
            for p in self.member.phone_set.filter(pagable=True):
                sms, created = OutboundSms.objects.get_or_create(
                    distribution=self, phone=p)
        if self.email:
            for e in self.member.email_set.filter(pagable=True):
                email, created = OutboundEmail.objects.get_or_create(
                    distribution=self, email=e)

    def rsvp_display(self):
        if self.rsvp:
            if self.rsvp_answer:
                return 'Yes'
            else:
                return 'No'
        else:
            return 'PENDING'


class OutboundMessageManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(sending_started=False)


class OutboundMessage(BaseModel):
    distribution = models.ForeignKey(Distribution, on_delete=models.CASCADE)
    destination = models.CharField(max_length=255, blank=True)
    sid = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    # The sending_started field is used to block the SMS worker thread
    # from retrying a failed send. This is so that if there is
    # something strange with one recepient that causes a crash, when
    # the worker restarts, it can continue sending the remainder in
    # the queue. It does NOT protect for thread safety. As written,
    # only one SMS worker may run at a time.
    sending_started = models.BooleanField(default=False)
    delivered = models.BooleanField(default=False)

    objects = models.Manager() # The default manager
    unsent = OutboundMessageManager()

    class Meta(BaseModel.Meta):
        abstract = True

    @property
    def display(self):
        return '{} : {}'.format(self.destination_display, self.status_display)

    @property
    def status_display(self):
        if self.error_message:
            return '{}: {}'.format(self.status, self.error_message)
        if self.status:
            return self.status
        return 'Created'


class OutboundSms(OutboundMessage):
    phone = models.ForeignKey(Phone, on_delete=models.CASCADE)
    error_code = models.IntegerField(blank=True, null=True)

    @property
    def e164(self):
        return phonenumbers.format_number(
            phonenumbers.parse(self.phone.number, 'US'),
            phonenumbers.PhoneNumberFormat.E164)

    @property
    def destination_display(self):
        if self.destination:
            return self.destination
        return self.e164

    def send(self):
        if self.sending_started:
            logger.error('send() called twice on sms {}'.format(self.pk))
            return
        self.sending_started = True
        self.save()
        e164 = self.e164
        self.destination = e164
        logger.info('Sending text to {}: {}'.format(self.destination,
                                                    self.distribution.text))

        kwargs = {
            'body': self.distribution.text,
            'to': e164,
            'from_': settings.TWILIO_SMS_FROM,
            'status_callback': 'http://{}{}'.format(
                settings.HOSTNAME, reverse('message:sms_callback')),
        }

        try:
            if settings.SMS_FILE_PATH:
                import json
                logfile = settings.SMS_FILE_PATH + '/sms.log'
                logger.info('Writing to file: {}'.format(logfile))
                with open(logfile, 'a') as f:
                    f.write(json.dumps(kwargs))
                    f.write('\n')
                message = Namespace(
                    sid='FAKE_' + uuid.uuid4().hex,
                    status='Delivered',
                    error_code=None,
                    error_message='',
                )
            else:
                # Import needed here to enable replacement for testing
                # and so developers without Twilio accounts can test
                # using the file output.
                from django_twilio.client import twilio_client
                message = twilio_client.messages.create(**kwargs)
        except twilio.base.exceptions.TwilioRestException as e:
            self.status = 'Twilio Error'
            self.error_code = e.code
            self.error_message = e.msg
            logger.error('Twilio error {} sending to {} using {}: {}'.format(
                e.code, e164, e.uri, e.msg))
        except Exception as e:
            self.status = 'ERROR'
            self.error_message = str(e)
            logger.error('Unknown twilio error {}: {}'.format(type(e), e))
        else:
            self.sid = message.sid
            self.status = message.status
            self.error_code = message.error_code
            self.error_message = message.error_message
        if self.error_message is None:
            self.error_message = ''
        self.save()


class InboundSms(BaseModel):
    sid = models.CharField(max_length=255, blank=True, null=True)
    from_number = models.CharField(max_length=255, blank=True, null=True)
    to_number = models.CharField(max_length=255, blank=True, null=True)
    body = models.CharField(max_length=255, blank=True, null=True)


class OutboundEmail(OutboundMessage):
    email = models.ForeignKey(Email, on_delete=models.CASCADE)
    opened = models.BooleanField(default=False)

    @property
    def destination_display(self):
        if self.destination:
            return self.destination
        return self.email.address

    def send(self):
        if self.sending_started:
            logger.error('send() called twice on email {}'.format(self.pk))
            return
        self.sending_started = True
        self.save()
        logger.info('Sending email to {}'.format(self.email.address))
        self.destination = self.email.address
        body = self.distribution.text
        html_body = self.distribution.html
        try:
            message = AnymailMessage(
                subject="BAMRU.net page",
                body=body,
                to=[self.destination],
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
            status = message.anymail_status.status
            if status:
                self.status = status.pop()
            else:
                self.status = 'No server status'
        self.save()
