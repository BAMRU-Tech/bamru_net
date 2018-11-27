from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from oauth2client import client, tools

from main.lib.gcal import get_token_store, GCAL_SCOPES

class Command(BaseCommand):
    def handle(self, *args, **options):
        flow = client.flow_from_clientsecrets(
            settings.GOOGLE_CREDENTIALS_FILE, GCAL_SCOPES)

        print("Be sure to authorize with the account that owns this calendar:",
            settings.GOOGLE_CALENDAR_ID)

        # I haven't figured out how to make oauth2lient.tools's argparser play
        # nice with django's. So just hardcode the flag to run headlessly.
        flags = tools.argparser.parse_args(['--noauth_local_webserver'])

        tools.run_flow(flow, get_token_store(), flags)
