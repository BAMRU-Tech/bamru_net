from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from main.models import Event, Member


class ActivityDetailReportTestCase(TestCase):
    def test_total_column_shows_member_hours_across_events(self):
        member = Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T')
        left = timezone.now() - timedelta(days=7)
        for hours in (2, 3):
            event = Event.objects.create(
                type='operation', title='Search {}'.format(hours),
                location='Somewhere', start_at=left,
                finish_at=left + timedelta(hours=hours))
            event.period_set.first().participant_set.create(
                member=member, en_route_at=left,
                return_home_at=left + timedelta(hours=hours))

        self.client.force_login(member)
        response = self.client.get('/reports/activity-detail/')

        self.assertContains(response, '<td>5.0</td>')
