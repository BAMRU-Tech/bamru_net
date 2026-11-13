import dateutil.parser
import googleapiclient.discovery
import googleapiclient.errors
from google.auth.exceptions import GoogleAuthError
from django.utils import timezone
from httplib2 import Http
from oauth2client import file, client, tools

from datetime import timedelta
from dynamic_preferences.registries import global_preferences_registry

import main.lib.oauth

import logging
logger = logging.getLogger(__name__)


def build_gcal_description(bamru_event, include_private):
    description_lines = []
    if bamru_event.leaders:
        description_lines.append("Leader(s): " + bamru_event.leaders)
    if include_private and bamru_event.description_private:
        description_lines.append(bamru_event.description_private)
        if bamru_event.description:
            description_lines.append("\nPublic description:")
    if bamru_event.description:
        description_lines.append(bamru_event.description)
    return '\n'.join(description_lines)

def build_gcal_event(bamru_event, include_private=False):
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
    if include_private and bamru_event.location_private:
        gcal_event['location'] = bamru_event.location_private
    elif bamru_event.location:
        gcal_event['location'] = bamru_event.location

    description = build_gcal_description(bamru_event, include_private)
    if description:
        gcal_event['description'] = description

    return gcal_event


class GcalManager:
    def __init__(self, client, calendar_id, calendar_id_private):
        self.client = client
        self.calendar_id = calendar_id
        self.calendar_id_private = calendar_id_private

    def sync_event(self, bamru_event, save=True):
        # Our approach is to delete this individual event if it exists and
        # recreate it if appropriate. A fancier approach would be to modify the
        # existing calendar event.

        if bamru_event.gcal_id:
            self.delete_for_event(bamru_event, False)
        
        if bamru_event.published:
            try:
                new_event = self.client.events().insert(
                    calendarId=self.calendar_id,
                    body=build_gcal_event(bamru_event, False),
                ).execute()
                bamru_event.gcal_id = new_event['id']
            except (googleapiclient.errors.HttpError, GoogleAuthError) as e:
                logger.error("Gcal create error " + str(e))
        else:
            bamru_event.gcal_id = None

        if bamru_event.published and self.calendar_id_private:
            try:
                new_event = self.client.events().insert(
                    calendarId=self.calendar_id_private,
                    body=build_gcal_event(bamru_event, True),
                ).execute()
                bamru_event.gcal_id_private = new_event['id']
            except (googleapiclient.errors.HttpError, GoogleAuthError) as e:
                logger.error("Gcal private create error " + str(e))
        else:
            bamru_event.gcal_id_private = None

        if save:
            bamru_event.save()

    def delete_for_event(self, bamru_event, save=True):
        if bamru_event.gcal_id:
            try:
                self.client.events().delete(
                    calendarId=self.calendar_id,
                    eventId=bamru_event.gcal_id,
                ).execute()
            except (googleapiclient.errors.HttpError, GoogleAuthError) as e:
                logger.error("Gcal delete error " + str(e))
            bamru_event.gcal_id = None

        if bamru_event.gcal_id_private:
            try:
                self.client.events().delete(
                    calendarId=self.calendar_id_private,
                    eventId=bamru_event.gcal_id_private,
                ).execute()
            except (googleapiclient.errors.HttpError, GoogleAuthError) as e:
                logger.error("Gcal private delete error " + str(e))
            bamru_event.gcal_id_private = None
       
        if save:
            bamru_event.save()


    def clear_public(self):
        """Clear only works on primary calendars.

        Used only by the sync_gcal manage command.
        """
        print("clearing existing events")
        self.client.calendars().clear(calendarId=self.calendar_id).execute()


    def clear_private(self):
        """Clear only works on primary calendars.

        Used only by the sync_gcal manage command.
        """
        print("clearing existing private events")
        self.client.calendars().clear(calendarId=self.calendar_id_private).execute()


    def _delete_from_calendar(self, calendar_id):
        """Remove all events from a calendar."""
        print("deleting all existing events from " + str(calendar_id))
        events = self.client.events().list(calendarId=calendar_id).execute()
        print("Found {} events to delete".format(len(events.get('items'))))
        for event in events.get('items'):
            print("deleting {} {} {}".format(
                event.get('id'),
                event.get('status'),
                event.get('summary'),
            ))
            print(self.client.events().delete(calendarId=calendar_id,
                                              eventId=event.get('id')).execute())

    def delete_public(self):
        """Remove all public events from a calendar.

        Can be used instead of clear() on a secondary calendar.
        """
        self._delete_from_calendar(self.calendar_id)


    def delete_private(self):
        """Remove all private events from a calendar.

        Can be used instead of clear() on a secondary calendar.
        """
        self._delete_from_calendar(self.calendar_id_private)


    def sync_public(self, all_bamru_events):
        batch_insert = self.client.new_batch_http_request()

        def make_cb(event):
            def cb(id, response, exception):
                if exception is None:
                    print("{} {}".format(id, response))
                    event.gcal_id = response['id']
                else:
                    print(str(exception))
                    event.gcal_id = None
                event.save()
            return cb

        print("building batch request")
        for event in all_bamru_events:
            if event.published:
                batch_insert.add(
                    self.client.events().insert(
                        calendarId=self.calendar_id,
                        body=build_gcal_event(event, False),
                    ),
                    callback=make_cb(event)
                )
            else:
                event.gcal_id = None

        print("executing batch request")
        print(batch_insert.execute())


    def sync_private(self, all_bamru_events):
        batch_insert = self.client.new_batch_http_request()

        def make_cb(event):
            def cb(id, response, exception):
                if exception is None:
                    print("{} {}".format(id, response))
                    event.gcal_id_private = response['id']
                else:
                    print(str(exception))
                    event.gcal_id_private = None
                event.save()
            return cb

        print("building batch request")
        for event in all_bamru_events:
            if event.published:
                batch_insert.add(
                    self.client.events().insert(
                        calendarId=self.calendar_id_private,
                        body=build_gcal_event(event, True),
                    ),
                    callback=make_cb(event)
                )
            else:
                event.gcal_id_private = None

        print("executing private batch request")
        print(batch_insert.execute())


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

def get_gcal_manager(fallback_manager=NoopGcalManager()):
    creds = main.lib.oauth.get_credentials()
    if not creds:
        logger.info("Google calendar creds not configured")
        return fallback_manager

    client = googleapiclient.discovery.build(
        'calendar', 'v3', credentials=creds, cache_discovery=False)
    global_preferences = global_preferences_registry.manager()
    return GcalManager(
        client,
        global_preferences['google__calendar_id_public'],
        global_preferences['google__calendar_id_private'])
