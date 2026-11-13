from google.oauth2 import service_account
import json

from dynamic_preferences.registries import global_preferences_registry

import logging
logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.group',
    'https://www.googleapis.com/auth/admin.directory.user',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
]

def get_credentials():
    global_preferences = global_preferences_registry.manager()
    service_account_json = global_preferences['google__credentials']
    try:
        service_account_info = json.loads(service_account_json)
    except json.decoder.JSONDecodeError as e:
        logger.info("Google credentials json parse error: " + str(e))
        return None

    try:
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES)
    except (FileNotFoundError, ValueError) as e:
        logger.info("Unable to load google credentials: {}".format(e))
        return None
    user = global_preferences['google__user']
    if not user:
        logger.info("Google user not configured")
        return None
    delegated_credentials = credentials.with_subject(user)
    return delegated_credentials
