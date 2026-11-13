from django.core.management.base import BaseCommand, CommandError

from main.models.event import Event
from main.lib.gcal import get_gcal_manager, NoopGcalManager

class Command(BaseCommand):
    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--event', type=int, help="Id of event to sync")
        group.add_argument('--all', action='store_true')
        group.add_argument('--all_public', action='store_true')
        group.add_argument('--all_private', action='store_true')

        group_all = parser.add_mutually_exclusive_group(required=True)
        group_all.add_argument('--clear', action='store_true')
        group_all.add_argument('--delete', action='store_true')
        group_all.add_argument('--add', action='store_true')

    def handle(self, *args, **options):
        gcal_manager = get_gcal_manager(fallback_manager=None)
        if gcal_manager is None:
            print("google calendar sync not configured")
            return

        if options['all'] or options['all_public']:
            if options['clear']:
                gcal_manager.clear_public()
            elif options['delete']:
                gcal_manager.delete_public()
            elif options['add']:
                gcal_manager.sync_public(Event.objects.all())
            else:
                print('Specify --clear, --delete, or --add.')
        if options['all'] or options['all_private']:
            if options['clear']:
                gcal_manager.clear_private()
            elif options['delete']:
                gcal_manager.delete_private()
            elif options['add']:
                gcal_manager.sync_private(Event.objects.all())
            else:
                print('Specify --clear, --delete, or --add.')
        if options['event']:
            event = Event.objects.get(id=options['event'])
            print(event.title, event.start_at, event.finish_at)
            print(event.gcal_id)
            gcal_manager.sync_event(event)
