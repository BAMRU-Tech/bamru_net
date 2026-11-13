from main.models import Member

import logging
logger = logging.getLogger(__name__)

def validate_login(uid, *args, **kwargs):
    """Find the user by matching UID to email."""
    members = Member.members.filter(profile_email__iexact=uid)
    if len(members) == 0:
        logger.warning('No user for {}'.format(uid))
    elif len(members) > 1:
        logger.error('Multiple users for {}: {}'.format(
            uid, ','.join(members)))
    else:
        user = members.first()
        return {
            'user': user,
            'is_new': user is None,
        }
