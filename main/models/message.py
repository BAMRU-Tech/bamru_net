import base64
import logging
import re
import uuid
import twilio
from argparse import Namespace
from datetime import datetime, timedelta

from anymail.message import AnymailMessage
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from main.lib.phone import format_e164
from .base import BaseModel, BasePositionModel, Configuration
from .event import Period
from .member import Email, Member, Phone

logger = logging.getLogger(__name__)

# Set this if the UI does not append the template
APPEND_RSVP_TEMPLATE = False

def get_next_sms_from_index(increment=True):
    """Gets the next SMS_FROM number from settings.  If increment,
    following messages will come from a new number. This is used when
    a RSVP response is expected in case the next text asks another
    question.
    """
    obj, created = Configuration.objects.get_or_create(
        key='sms_sender_index', defaults={'value': '0'})
    try:
        index = int(obj.value)
    except ValueError as e:
        index = 0
    if index >= len(settings.TWILIO_SMS_FROM):
        index = 0
    sms_from_index = index
    if increment:
        index += 1
    obj.value = str(index)
    obj.save()
    return sms_from_index

class RsvpTemplate(BasePositionModel):
    name = models.CharField(max_length=255, blank=True, null=True)
    prompt = models.CharField(max_length=255, blank=True, null=True)
    yes_prompt = models.CharField(max_length=255, blank=True, null=True)
    no_prompt = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

    def html(self, unauth_rsvp_token):
        yn = ''.join(['<p><a href="http://{}{}">{}</a></p>'
                      .format(settings.HOSTNAME,
                              reverse('unauth_rsvp',
                                      args=[unauth_rsvp_token, yn]),
                              prompt)
                      for yn, prompt in
                      (('yes', self.yes_prompt), ('no', self.no_prompt))])
        if APPEND_RSVP_TEMPLATE:
            return '<p>{}</p>{}'.format(self.prompt, yn)
        return yn

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
        ('test', 'test'),
    )
    author = models.ForeignKey(Member, on_delete=models.CASCADE)
    text = models.TextField()
    format = models.CharField(choices=FORMATS, max_length=255)
    linked_rsvp = models.ForeignKey(
        'self', on_delete=models.SET_NULL, blank=True, null=True)
    ancestry = models.CharField(max_length=255, blank=True, null=True)
    period = models.ForeignKey(
        Period, on_delete=models.SET_NULL, blank=True, null=True)
    period_format = models.CharField(
        choices=PERIOD_FORMATS, max_length=255, blank=True, null=True)
    rsvp_template = models.ForeignKey(
        RsvpTemplate, on_delete=models.SET_NULL, blank=True, null=True)

    def get_absolute_url(self):
        return reverse('message_detail', args=[str(self.id)])

    def ancestry_messages(self):
        if not self.ancestry:
            return []
        messages = []
        for a in self.ancestry.split(','):
            try:
                messages.append(Message.objects.get(id=a.strip()))
            except Message.DoesNotExist:
                logger.error('Ancestor {} not found for {}'.format(a, self.id))
        return messages

    def ancestry_links(self):
        return ", ".join([
            '<a href="{}">{}</a>'.format(m.get_absolute_url(), m.id)
            for m in self.ancestry_messages()])

    def descendant_messages(self):
        return Message.objects.filter(ancestry__contains=self.id)

    def associated_messages(self):
        return list(self.descendant_messages()) + self.ancestry_messages()

    @property
    def time_slug(self):
        timestamp = int(self.created_at.timestamp())
        timeb = timestamp.to_bytes((timestamp.bit_length() // 8) + 1, 'big')
        return base64.b85encode(timeb).decode()

    @property
    def expanded_text(self):
        if APPEND_RSVP_TEMPLATE and self.rsvp_template:
            return '{} {}'.format(self.text, self.rsvp_template.text)
        return self.text

    def html(self, unauth_rsvp_token):
        # TODO: Use a Django template for this
        html_body = ''
        html_body += '<h3>Message:</h3><p>{}</p>'.format(self.text)
        if self.rsvp_template:
            html_body += self.rsvp_template.html(unauth_rsvp_token)
        if self.period:
            url = 'http://{}{}'.format(settings.HOSTNAME,
                                       self.period.event.get_absolute_url())
            html_body += '<h3>Event:</h3><p><a href="{}">{}</a></p>'.format(
                url, self.period)
        html_body += '<h3>Sent by:</h3><p>{}<br>{}<br>{}</p>'.format(
            self.author, self.author.display_phone, self.author.display_email)
        return html_body

    def queue(self):
        """
        Queues the message for sending.
        Because sending can take some time, we only create the OutgoingMessages.
        Actual sending is done in the message_send task.
        """
        increment = ((self.rsvp_template is not None) and
                     (self.distribution_set.filter(send_sms=True).count() > 0))
        sms_from_index = get_next_sms_from_index(increment)
        logger.info('sending {} from index {}'.format(str(self), sms_from_index))
        for d in self.distribution_set.all():
            # Use member id to rotate index in order to reduce the
            # number of SMS messages from the same number. Too many
            # was causing messages to be dropped.
            member_index = ((sms_from_index + d.member.id) %
                            len(settings.TWILIO_SMS_FROM))
            sms_from = format_e164(settings.TWILIO_SMS_FROM[member_index])
            logger.debug('member {} from index {} => {}'.format(
                d.member.id, member_index, sms_from))
            d.queue(sms_from)


class Distribution(BaseModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    send_email = models.BooleanField(default=False)
    send_sms = models.BooleanField(default=False)
    read = models.BooleanField(default=False)
    bounced = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    response_seconds = models.IntegerField(blank=True, null=True)
    rsvp = models.BooleanField(default=False)
    rsvp_answer = models.NullBooleanField()
    unauth_rsvp_token = models.CharField(
        max_length=255, unique=True, null=True, default=uuid.uuid4, editable=False)
    unauth_rsvp_expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return 'Message {} to {}'.format(
            self.message.id, self.member)

    @property
    def text(self):
        return self.message.expanded_text

    @property
    def html(self):
        return self.message.html(self.unauth_rsvp_token)

    def queue(self, sms_from):
        self.unauth_rsvp_expires_at = timezone.now() + timedelta(hours=24)
        self.save()
        if self.send_sms:
            for p in self.member.phone_set.filter(pagable=True):
                sms, created = OutboundSms.objects.get_or_create(
                    distribution=self, phone=p,
                    defaults={'source':sms_from})
        if self.send_email:
            for e in self.member.email_set.filter(pagable=True):
                email, created = OutboundEmail.objects.get_or_create(
                    distribution=self, email=e)

    def handle_rsvp(self, rsvp):
        self.rsvp = True
        self.rsvp_answer = rsvp
        if not self.response_seconds:
            delta = timezone.now() - self.created_at
            self.response_seconds = delta.total_seconds()
        self.save()

    def rsvp_display(self):
        if self.rsvp:
            if self.rsvp_answer:
                return 'Yes'
            else:
                return 'No'
        else:
            return 'PENDING'

    def response_time(self):
        day = self.created_at.date()
        if self.member.unavailable_set.filter(
            start_on__lte=day, end_on__gte=day).count() > 0:
            return 'unavail'
        s = self.response_seconds
        if s is None:
            return '-'
        return s

    def response_time_display(self):
        s = self.response_time()
        if not isinstance(s, int):
            return s
        if s < 60:
            return '{0:.0f} s'.format(s)
        if s < 3600:
            return '{0:.0f} m'.format(s / 60)
        return '{0:.1f} hr'.format(s / 3600)


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
    phone = models.ForeignKey(Phone, on_delete=models.SET_NULL, null=True)
    error_code = models.IntegerField(blank=True, null=True)
    source = models.CharField(max_length=255, blank=True)

    @property
    def e164(self):
        return format_e164(self.phone.number)

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
        logger.info('Sending text to {} from {}: {}'.format(
            self.destination,
            self.source,
            self.distribution.text))

        kwargs = {
            'body': self.distribution.text,
            'to': e164,
            'from_': self.source,
            'status_callback': 'http://{}{}'.format(
                settings.HOSTNAME, reverse('sms_callback')),
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
    member = models.ForeignKey(Member, null=True, on_delete=models.SET_NULL)
    outbound = models.ForeignKey(OutboundSms, null=True, on_delete=models.SET_NULL)
    yes = models.BooleanField(default=False)
    no = models.BooleanField(default=False)
    extra_info = models.BooleanField(default=False)

    @staticmethod
    def has_extra_info(text):
        # Match the common yes/no variants (allow period & whitespace at end).
        # Also ignore a single emoji at the end (phone autofill).
        # There is an actual message if this regex does not match.
        return (re.compile(r"""(
                                (y(es|ep|eah?)?)|
                                (no?(pe)?)
                               )[.]?\s*[\u263a-\U0001f645]?\s*$""",
                           re.IGNORECASE | re.VERBOSE)
                .match(text) is None)

    def process(self):
        """Calculate member and outbound using from/to."""
        hours = 24
        date_from = self.created_at - timedelta(hours=hours)
        qs = OutboundSms.objects.filter(
            destination=self.from_number,
            source=self.to_number,
            created_at__gte=date_from)
        self.outbound = (qs.filter(distribution__message__rsvp_template__isnull=False)
                         .order_by('-pk').first())
        if self.outbound:
            self.member = self.outbound.distribution.member
        else:
            out2 = qs.order_by('-pk').first()
            if out2:
                self.member = out2.distribution.member

        if self.body:
            yn = self.body[0].lower()
            self.yes = (yn == 'y')
            self.no = (yn == 'n')

        self.extra_info = self.has_extra_info(self.body)

        self.save()


class OutboundEmail(OutboundMessage):
    email = models.ForeignKey(Email, on_delete=models.SET_NULL, null=True)
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
                subject="BAMRU.net page [{}]".format(
                    self.distribution.message.time_slug),
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
