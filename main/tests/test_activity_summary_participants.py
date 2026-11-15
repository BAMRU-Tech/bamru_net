from datetime import UTC, datetime, timedelta

from django.test import TestCase
from model_mommy import mommy

from main.models import Member, Participant


class ActivitySummaryParticipantsTestCase(TestCase):
    """Each event type's participant count on the Unit-wide Summary is the
    number of distinct members with hours at that type, not the number of
    attendances. The example from issue #694."""
    URL = '/reports/activity-summary/?start=2024-01-01&end=2024-12-31'

    @classmethod
    def attend(cls, member, event_type, day):
        """Two hours at a new event of event_type on 2024-06-<day>."""
        left = datetime(2024, 6, day, tzinfo=UTC)
        mommy.make(Participant, member=member,
                   period__event__type=event_type,
                   period__event__start_at=left,
                   en_route_at=left,
                   return_home_at=left + timedelta(hours=2))

    @classmethod
    def setUpTestData(cls):
        cls.user = mommy.make(Member, status='T')
        member_a = mommy.make(Member, status='TM')
        member_b = mommy.make(Member, status='TM')
        for day in (1, 2, 3):
            cls.attend(member_a, 'training', day)
        cls.attend(member_a, 'meeting', 4)
        cls.attend(member_b, 'training', 5)

    def setUp(self):
        self.client.force_login(self.user)
        self.context = self.client.get(self.URL).context

    def testCountsEachMemberOncePerEventType(self):
        type_totals = self.context['unit_type_totals']
        self.assertEqual(type_totals['training'], [2, 8])
        self.assertEqual(type_totals['meeting'], [1, 2])
        self.assertEqual(type_totals['operation'], [0, 0])

    def testTotalRowIsUnchanged(self):
        self.assertEqual(self.context['unit_totals'], [2, 10])
