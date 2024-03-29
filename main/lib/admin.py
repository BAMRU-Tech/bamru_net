# Google admin API

import googleapiclient.discovery
import googleapiclient.errors
import main.lib.oauth

import logging
logger = logging.getLogger(__name__)

class NoopAdminDirectory:
    """Exposes the same methods, but doesn't do anything."""
    def __init__(self):
        pass

    def update_user(self, userKey, data):
        return ''


class AdminDirectory(NoopAdminDirectory):
    def __new__(cls):
        instance = super(AdminDirectory, cls).__new__(cls)
        c = main.lib.oauth.get_credentials()
        if not c:
            return NoopAdminDirectory()
        instance.directory = googleapiclient.discovery.build(
            'admin', 'directory_v1', credentials=c, cache_discovery=False)
        if not instance.directory:
            return NoopAdminDirectory()
        return instance

    def update_user(self, userKey, data):
        try:
            return self.directory.users().update(
                userKey=userKey,
                body=data,
            ).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))
            return ''
