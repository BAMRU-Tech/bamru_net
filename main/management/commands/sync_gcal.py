from django.core.management.base import BaseCommand, CommandError

from main.models.event import Event
from main.lib.gcal import default_gcal_manager

class Command(BaseCommand):
    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--event', type=int, help="Id of event to sync")
        group.add_argument('--all', action='store_true')

    def handle(self, *args, **options):
        if options['all']:
            default_gcal_manager().sync_all(Event.objects.all())
        elif options['event']:
            event = Event.objects.get(id=options['event'])
            print(event.title, event.start_at, event.finish_at)
            print(event.gcal_id)
            default_gcal_manager().sync_event(event)
