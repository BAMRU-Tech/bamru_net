from django.utils import timezone

import logging
from datetime import timedelta
from django_q.tasks import async_task
from dynamic_preferences.registries import global_preferences_registry
import urllib.request

from .lib import groups
from .models import Cert, Distribution, DoLog, Event, Member, Message, OutboundEmail, OutboundSms, Participant, Role

logger = logging.getLogger(__name__)

from opentelemetry import trace
tracer = trace.get_tracer(__name__)


# @shared_task
def debug_print(text):
    response = 'Debug print: {}'.format(text)
    logger.info(response)
    return response

# @shared_task
@tracer.start_as_current_span("task_http_get")
def http_get(url):
    """Can be used to poll a health check URL."""
    return urllib.request.urlopen(url).read()

# @shared_task
@tracer.start_as_current_span("message_send")
def message_send(message_id):
    """Task to actually do the message sending.

    The message_id is only for logging purposes. We do not want any
    state needed in the message queue.
    """
    logger.info('Running message_send triggered by {}'.format(message_id))
    # TODO: separate worker threads for sms/email
    for sms in OutboundSms.unsent.all():
        sms.send()
    for email in OutboundEmail.unsent.all():
        email.send()

def send_cert_notice(cert, text, author, cc=[]):
    if not cert.member.status.is_current:
        logger.info('Skipping sending cert expiration notice to {}: {}'
                    .format(cert.member, text))
        return
    logger.info('Sending cert expiration notice: {}'.format(text))
    message = Message.objects.create(
        author=author, text=text, format='cert_notice')
    for dest in [cert.member] + cc:
        dist = Distribution.objects.create(
            message=message, member=dest, send_email=True)
        dist.queue(None)

# @shared_task
def cert_notice_check():
    global_preferences = global_preferences_registry.manager()
    if not global_preferences['general__cert_notice']:
        logger.info('Skiping cert notice check')
        return
    now = timezone.now()
    date30 = now + timedelta(days=30)
    date90 = now + timedelta(days=90)
    neg30 = now - timedelta(days=30)  # don't look too far in past

    cert90 = Cert.objects.filter(expires_on__gt=date30, expires_on__lte=date90,
                                 ninety_day_notice_sent_at__isnull=True)
    cert30 = Cert.objects.filter(expires_on__gt=now, expires_on__lte=date30,
                                 thirty_day_notice_sent_at__isnull=True)
    cert0 = Cert.objects.filter(expires_on__gt=neg30, expires_on__lte=now,
                                expired_notice_sent_at__isnull=True)

    oo = Role.objects.filter(role='OO').first().member

    for cert in cert90:
        text = '{}, your "{}" {} cert expires on {}'.format(
            cert.member, cert.description, cert.get_type_display(), cert.expires_on)
        send_cert_notice(cert, text, oo, [])
        cert.ninety_day_notice_sent_at = now
        cert.save()
    for cert in cert30:
        text = 'One month warning! {}, your "{}" {} cert expires on {}'.format(
            cert.member, cert.description, cert.get_type_display(), cert.expires_on)
        send_cert_notice(cert, text, oo, [])
        cert.thirty_day_notice_sent_at = now
        cert.save()
    for cert in cert0:
        text = '{}, your "{}" {} cert has expired!'.format(
            cert.member, cert.description, cert.get_type_display())
        send_cert_notice(cert, text, oo, [oo])
        cert.expired_notice_sent_at = now
        cert.save()

    if cert90.count() + cert30.count() + cert0.count() > 0:
        async_task(message_send, 'certs')


# @shared_task
def meeting_sign_in_update():
    participants = Participant.objects.filter(
        en_route_at__isnull=True,
        return_home_at__isnull=True,
        signed_in_at__isnull=True,
        signed_out_at__isnull=True,
        period__event__type='meeting',
        period__event__all_day=False,
        period__event__finish_at__lt=timezone.now()
    )
    for p in participants:
        logger.info('Auto sign in {} for {}'.format(p.member, p.period.event))
        p.signed_in_at = p.period.event.start_at
        p.signed_out_at = p.period.event.finish_at
        p.save()

# @shared_task
def set_do(member_id, is_do):
    logger.info('Running set_do triggered by {}, {}'.format(member_id, is_do))
    member = Member.objects.get(id=member_id)
    logger.info('Setting {} DO={}'.format(member, is_do))
    member.is_current_do = is_do
    member.save()
    do_group = groups.get_do_group()
    for email in member.pagable_email_addresses():
        if is_do:
            do_group.insert(email)
        else:
            do_group.delete(email)
    if is_do:
        DoLog.current_do_log().add_writer(member)
    # No else - do not remove writers from DO Log.

# @shared_task
def event_create_aar(event_id):
    logger.info('Running event_create_aar triggered by {}'.format(event_id))
    Event.objects.get(id=event_id).create_aar()

# @shared_task
def event_create_ahc_log(event_id):
    logger.info('Running event_create_ahc_log triggered by {}'.format(event_id))
    Event.objects.get(id=event_id).create_ahc_log()

# @shared_task
def event_create_logistics_spreadsheet(event_id):
    logger.info('Running event_create_logistics_spreadsheet triggered by {}'.format(event_id))
    Event.objects.get(id=event_id).create_logistics_spreadsheet()

# @shared_task
@tracer.start_as_current_span("member_update_all_google_profiles")
def member_update_all_google_profiles():
    [x.update_google_profile() for x in Member.objects.all()]

# @shared_task
@tracer.start_as_current_span("member_update_all_profile_emails")
def member_update_all_profile_emails():
    [x.profile_email_to_email_set() for x in Member.objects.all()]
