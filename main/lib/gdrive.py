# Google drive API

import googleapiclient.discovery
import googleapiclient.errors
import main.lib.oauth
from main.models import Configuration

import logging
logger = logging.getLogger(__name__)

class NoopGoogleDrive:
    """Exposes the same methods, but doesn't do anything."""
    def __init__(self):
        pass

    def add_writer(self, fileId, email):
        return ''

    def file_copy(self, templateId, destinationId, name):
        return ''


class GoogleDrive(NoopGoogleDrive):
    def __new__(cls):
        instance = super(GoogleDrive, cls).__new__(cls)
        c = main.lib.oauth.get_credentials()
        if not c:
            return NoopGoogleDrive()
        instance.drive = googleapiclient.discovery.build(
            'drive', 'v3', credentials=c, cache_discovery=False)
        if not instance.drive:
            return NoopGoogleDrive()
        return instance

    def _add_permission(self, fileId, email, role, notify):
        permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email,
        }
        try:
            return self.drive.permissions().create(
                fileId=fileId,
                supportsAllDrives=True,
                sendNotificationEmail=notify,
                body=permission,
            ).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))
            return ''

    def add_writer(self, fileId, email, notify=False):
        return self._add_permission(fileId, email, 'writer', notify)

    def file_copy(self, templateId, destinationId, name):
        dest_file = {'name': name, 'parents' : [destinationId]}
        try:
            result = self.drive.files().copy(
                fileId=templateId,
                supportsAllDrives=True,
                body=dest_file
            ).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))
            return ''
        logger.info(result)
        return result.get('id', '')
