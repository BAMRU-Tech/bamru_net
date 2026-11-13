from datetime import UTC, datetime, timedelta

from django.test import Client, TestCase
from model_mommy import mommy

from main.models import (
        Address,
        Email,
        EmergencyContact,
        Member,
        Participant,
        Phone,
        Role,
)

from random import random, randint

import sys

import logging
logger = logging.getLogger(__name__)


class RosterTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Add a few members with different amounts of info. May not be an
        # exhaustive test. Also, random initialization is asking for trouble,
        # but since that's what model_mommy does, I doubled down on it.s
        # TODO replace this with manual initialization that covers all the
        # cases we think might be interesting.
        cls.members = []
        for i in range(10):
            member = mommy.make(Member, is_active=True, _fill_optional=True)
            for i in range(randint(0, 3)):
                mommy.make(Address, member=member, _fill_optional=True)
            for i in range(randint(0, 3)):
                mommy.make(Email, member=member, _fill_optional=True)
            for i in range(randint(0, 3)):
                mommy.make(EmergencyContact, member=member, _fill_optional=True)
            for i in range(randint(0, 3)):
                mommy.make(Phone, member=member,
                           number=randint(1000000, 9999999),
                           _fill_optional=True)
            if member.status in ['TM', 'FM', 'T']:
                mommy.make(Role, member=member, role=member.status)
                if member.status in ['TM', 'FM'] and random() < 0.2:
                    mommy.make(Role, member=member, role='OL')
            cls.members.append(member)

        # This is the user we'll make requests as. Make sure they can log in.
        cls.user = cls.members[0]
        if cls.user.status not in ['TM', 'FM', 'T']:
            cls.user.status = 'T'
            cls.user.is_active = True
            cls.user.save()
            mommy.make(Role, member=cls.user, role=cls.user.status)

    def setUp(self):
        self.client = Client()

    def assertResponseContainsMembers(self, response):
        for m in self.members:
            if m.status in ['TM', 'FM', 'T']:
                self.assertIn(m.first_name, response.content.decode('utf-8'))
                self.assertIn(m.last_name, response.content.decode('utf-8'))

    def testFull(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-full.html')
        self.assertEqual(response.status_code, 200)
        self.assertResponseContainsMembers(response)

    def testField(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-field.html')
        self.assertEqual(response.status_code, 200)
        self.assertResponseContainsMembers(response)

    def testWallet(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-wallet.html')
        self.assertEqual(response.status_code, 200)
        self.assertResponseContainsMembers(response)

    def testNames(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-names.html')
        self.assertEqual(response.status_code, 200)
        self.assertResponseContainsMembers(response)

    def testCsv(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-roster.csv')
        self.assertEqual(response.status_code, 200)
        self.assertResponseContainsMembers(response)

    def testVcf(self):
        self.client.force_login(self.user)
        response = self.client.get('/reports/roster/BAMRU-roster.vcf')
        self.assertEqual(response.status_code, 200)
        for m in self.members:
            if m.status in ['TM', 'FM', 'T']:
                # The vcard format has line breaks, don't bother trying to
                # parse it, just sanity check.
                self.assertIn(m.first_name[:20], response.content.decode('utf-8'))
                self.assertIn(m.last_name[:20], response.content.decode('utf-8'))


class ActivitySummaryTestCase(TestCase):
    """The report lists everyone with hours in the period, plus current
    members whose first event was before the period ended. Guests are not
    listed."""
    URL = '/reports/activity-summary/?start=2024-01-01&end=2024-12-31'
    BEFORE_PERIOD = datetime(2023, 6, 1, tzinfo=UTC)
    IN_PERIOD = datetime(2024, 6, 1, tzinfo=UTC)
    AFTER_PERIOD = datetime(2025, 6, 1, tzinfo=UTC)

    @classmethod
    def make_member(cls, last_name, status, event_at=None):
        """Create a member, with two hours at an event if event_at is given."""
        member = mommy.make(Member, status=status, last_name=last_name)
        if event_at:
            mommy.make(Participant, member=member,
                       period__event__type='training',
                       period__event__start_at=event_at,
                       en_route_at=event_at,
                       return_home_at=event_at + timedelta(hours=2))

    @classmethod
    def setUpTestData(cls):
        cls.user = mommy.make(Member, status='T')
        cls.make_member('CurrentWithHours', 'TM', cls.IN_PERIOD)
        cls.make_member('CurrentWithEarlierEvent', 'TM', cls.BEFORE_PERIOD)
        cls.make_member('CurrentWithLaterEvent', 'T', cls.AFTER_PERIOD)
        cls.make_member('CurrentWithNoEvent', 'T')
        cls.make_member('AlumWithHours', 'MA', cls.IN_PERIOD)
        cls.make_member('AlumWithoutHours', 'MA')
        cls.make_member('NoContactWithHours', 'MN', cls.IN_PERIOD)
        cls.make_member('NoContactWithoutHours', 'MN')
        cls.make_member('GuestWithHours', 'G', cls.IN_PERIOD)

    def setUp(self):
        self.client.force_login(self.user)
        self.report = self.client.get(self.URL).content.decode('utf-8')

    def testListsCurrentMembersWithAnEventByPeriodEnd(self):
        self.assertIn('CurrentWithHours', self.report)
        self.assertIn('CurrentWithEarlierEvent', self.report)

    def testListsAlumAndNoContactWithHoursInPeriod(self):
        self.assertIn('AlumWithHours', self.report)
        self.assertIn('NoContactWithHours', self.report)

    def testOmitsCurrentMembersWithNoEventByPeriodEnd(self):
        self.assertNotIn('CurrentWithLaterEvent', self.report)
        self.assertNotIn('CurrentWithNoEvent', self.report)

    def testOmitsAlumAndNoContactWithoutHoursInPeriod(self):
        self.assertNotIn('AlumWithoutHours', self.report)
        self.assertNotIn('NoContactWithoutHours', self.report)

    def testOmitsGuests(self):
        self.assertNotIn('GuestWithHours', self.report)
