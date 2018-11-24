from django.core.management.base import BaseCommand, CommandError

from oauth2client import tools

from main.lib.gcal import default_token_store, default_oauth_flow

class Command(BaseCommand):
    def handle(self, *args, **options):
        print( args, options)
        store = default_token_store()
        flow = default_oauth_flow()

        # I haven't figured out how to make oauth2lient.tools's argparser play
        # nice with django's. So just hardcode the flag to run headlessly.
        flags = tools.argparser.parse_args(['--noauth_local_webserver'])

        tools.run_flow(default_oauth_flow(), default_token_store(), flags)
