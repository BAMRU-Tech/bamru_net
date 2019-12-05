import googleapiclient
import main.lib.oauth
from main.models import Configuration

import logging
logger = logging.getLogger(__name__)


class NoopGoogleGroup:
    """Exposes the same methods, but doesn't do anything."""
    def __init__(self):
        self.name = 'dummy_group@example.com'

    def list_emails(self):
        """Returns a list of emails that are members of the group."""
        return [x.get('email') for x in self.list()]

    def list(self):
        return []

    def insert(self, email):
        return ''

    def remove(self, email):
        return ''


class GoogleGroup(NoopGoogleGroup):
    def __new__(cls, name):
        instance = super(GoogleGroup, cls).__new__(cls)
        c = main.lib.oauth.get_credentials()
        admin = googleapiclient.discovery.build(
            'admin', 'directory_v1', credentials=c)
        if not name or not admin:
            return NoopGoogleGroup()
        instance.members = admin.members()
        return instance

    def __init__(self, name):
        self.name = name

    def list(self):
        """Returns a list of user objects that are members of the group.
        Example:
        {'email': 'a@example.com',
         'etag': 'XXX',
         'kind': 'admin#directory#member',
         'role': 'MEMBER',
         'id': '123',
         'status': 'ACTIVE',
         'type': 'USER'}
        """
        try:
            response = self.members.list(groupKey=self.name).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))
            return []
        return response.get('members')

    def insert(self, email):
        # Catches googleapiclient.errors.HttpError on duplicate.
        body = {'email': email}
        try:
            return self.members.insert(groupKey=self.name, body=body).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))

    def delete(self, email):
        # Catches googleapiclient.errors.HttpError on missing.
        try:
            self.members.delete(groupKey=self.name,
                                memberKey=email).execute()
        except googleapiclient.errors.HttpError as e:
            logger.error(str(e))

def get_do_group():
    return GoogleGroup(Configuration.get_host_key('do_group'))
