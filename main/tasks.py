from django.conf import settings
from django.utils import timezone

import logging
from datetime import timedelta

from .models import Cert, Configuration, Distribution, Member, Message, OutboundEmail, OutboundSms, Role

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def debug_print(text):
    logger.info('Debug print: {}'.format(text))

@shared_task
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
    if cert.member.status not in Member.CURRENT_MEMBERS:
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

@shared_task
def cert_notice_check():
    key = 'cert_notice_{}'.format(settings.HOSTNAME)
    if not Configuration.objects.filter(key=key).first():
        logger.info('Skiping cert notice check ({})'.format(key))
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
        message_send.delay('certs')
