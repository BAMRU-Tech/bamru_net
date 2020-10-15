from google.oauth2 import service_account

from django.conf import settings
from main.models import Configuration

import logging
logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group',
    'https://www.googleapis.com/auth/admin.directory.user',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
]

def get_credentials():
    if not (settings.GOOGLE_CREDENTIALS_FILE):
        logger.info("Google credentials not configured")
        return None

    try:
        credentials = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    except (FileNotFoundError, ValueError) as e:
        logger.info("Unable to load google credentials: {}".format(e))
        return None
    user = Configuration.get_host_key('google_user')
    if not user:
        logger.info("Google user not configured")
        return None
    delegated_credentials = credentials.with_subject(user)
    return delegated_credentials
