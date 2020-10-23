from main.models import Email

import logging
logger = logging.getLogger(__name__)

def validate_login(uid, *args, **kwargs):
    """Find the user by matching UID to email."""
    emails = Email.objects.filter(address=uid)
    if len(emails) == 0:
        logger.warning('No user for {}'.format(uid))
    elif len(emails) > 1:
        logger.warning('Multiple users for {}: {}'.format(
            uid, ','.join(emails)))
    else:
        user = emails.first().member
        return {
            'user': user,
            'is_new': user is None,
        }
