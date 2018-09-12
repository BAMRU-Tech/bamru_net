import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def message_send(message_id):
    from .models import Message  # Here to avoid circular dependency
    logger.info('Running message_send {}'.format(message_id))
    Message.objects.get(id=message_id).send()
