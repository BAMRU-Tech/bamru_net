import logging

from celery import shared_task

from .models import Message

logger = logging.getLogger(__name__)


@shared_task
def message_send(message_id):
    logger.info('Running message_send {}'.format(message_id))
    Message.objects.get(id=message_id).send()
