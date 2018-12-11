import dateutil.parser
import googleapiclient.discovery
from django.conf import settings
from django.utils import timezone
from httplib2 import Http
from oauth2client import file, client, tools

from datetime import timedelta

import logging
logger = logging.getLogger(__name__)


# If this is modified, a new token will be needed.
GCAL_SCOPES = 'https://www.googleapis.com/auth/calendar'

def build_gcal_description(bamru_event):
    description_lines = []
    if bamru_event.leaders:
        description_lines.append("Leader(s): " + bamru_event.leaders)
    if bamru_event.description:
        description_lines.append(bamru_event.description)
    return '\n'.join(description_lines)

def build_gcal_event(bamru_event):
    start_dt = timezone.localtime(bamru_event.start_at)
    end_dt = timezone.localtime(bamru_event.finish_at)

    if bamru_event.all_day:
        start = {'date': start_dt.date().isoformat()}
        # Add one day since gcal end dates/times are exclusive.
        end = {'date': (end_dt.date() + timedelta(days=1)).isoformat()}
    else:
        start = {'dateTime': start_dt.isoformat()}
        end = {'dateTime': end_dt.isoformat()}

    print(start, end)

    gcal_event = {
        'start': start,
        'end': end,
        'summary': bamru_event.title,
    }
    if bamru_event.location:
        gcal_event['location'] = bamru_event.location

    description = build_gcal_description(bamru_event)
    if description:
        gcal_event['description'] = description

    return gcal_event


class GcalManager:
    def __init__(self, client, calendar_id):
        self.client = client
        self.calendar_id = calendar_id

    def sync_event(self, bamru_event, save=True):
        # Our approach is to delete this individual event if it exists and
        # recreate it if appropriate. A fancier approach would be to modify the
        # existing calendar event.

        if bamru_event.gcal_id:
            self.delete_for_event(bamru_event, False)
        
        if bamru_event.published:
            new_event = self.client.events().insert(
                calendarId=self.calendar_id,
                body=build_gcal_event(bamru_event),
            ).execute()
            bamru_event.gcal_id = new_event['id']
        else:
            bamru_event.gcal_id = None

        if save:
            bamru_event.save()

    def delete_for_event(self, bamru_event, save=True):
        if bamru_event.gcal_id:
            self.client.events().delete(
                calendarId=self.calendar_id,
                eventId=bamru_event.gcal_id,
            ).execute()
            bamru_event.gcal_id = None
       
        if save:
            bamru_event.save()

    def sync_all(self, all_bamru_events):
        batch_insert = self.client.new_batch_http_request()

        def make_cb(event):
            def cb(id, response, exception):
                if exception is None:
                    event.gcal_id = response['id']
                else:
                    event.gcal_id = None
                event.save()
            return cb

        print("building batch request")
        for event in all_bamru_events:
            if event.published:
                batch_insert.add(
                    self.client.events().insert(
                        calendarId=self.calendar_id,
                        body=build_gcal_event(event),
                    ),
                    callback=make_cb(event)
                )
            else:
                event.gcal_id = None

        print("clearing existing events")
        self.client.calendars().clear(calendarId=self.calendar_id).execute()
        print("executing batch request")
        batch_insert.execute()


class NoopGcalManager:
    # Calls save() on events to maintain compatibility with full class;
    # otherwise doesn't do anything.

    def sync_event(self, bamru_event, save=True):
        if save:
            bamru_event.save()

    def delete_for_event(self, bamru_event, save=True):
        if save:
            bamru_event.save()

    def sync_all(self, all_bamru_events):
        for event in all_bamru_events:
            event.save()


def get_token_store():
    return file.Storage(settings.GOOGLE_TOKEN_FILE)

def get_gcal_manager(fallback_manager=NoopGcalManager()):
    if not (settings.GOOGLE_TOKEN_FILE and settings.GOOGLE_CALENDAR_ID):
        logger.info("Google calendar not configured")
        return fallback_manager

    creds = get_token_store().get()
    if not creds or creds.invalid:
        logger.error("Bad google calendar oauth credentials!")
        return fallback_manager

    client = googleapiclient.discovery.build(
        'calendar', 'v3', http=creds.authorize(Http()))
    return GcalManager(client, settings.GOOGLE_CALENDAR_ID)
