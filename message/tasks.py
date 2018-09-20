import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def message_send(message_id):
    """Task to actually do the message sending.

    The message_id is only for logging purposes. We do not want any
    state needed in the message queue.
    """
    # Import here to avoid circular dependency
    from .models import OutboundEmail, OutboundSms
    logger.info('Running message_send {}'.format(message_id))
    # TODO: separate worker threads for sms/email
    for sms in OutboundSms.objects.filter(status=""):
        sms.send()
    for email in OutboundEmail.objects.filter(status=""):
        email.send()
