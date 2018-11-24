from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from main.models.event import Event

from datetime import timedelta

import sys


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--it-is-during-the-database-import', action='store_true')

    def handle(self, *args, **options):
        if not options['it_is_during_the_database_import']:
            print("This should only be run once, when importing the database.")
            sys.exit(1)

        for e in Event.objects.filter(all_day=True):
            e.start_at = timezone.localtime(e.start_at)
            e.finish_at = timezone.localtime(e.finish_at)

            # Normalize start and finish times
            e.start_at = e.start_at.replace(hour=0, minute=0)
            e.finish_at = e.finish_at.replace(hour=23, minute=59)

            e.save()
