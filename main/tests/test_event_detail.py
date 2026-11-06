from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from dynamic_preferences.registries import global_preferences_registry

from main.models import DoAvailable, Event, Member
from main.models.member import Phone


class EventDetailEsbCopyTestCase(TestCase):
    def setUp(self):
        self.viewer = Member.objects.create(
            username='john doe', first_name='John', last_name='Doe', status='T')
        self.searcher = Member.objects.create(
            username='jane roe', first_name='Jane', last_name='Roe', status='T')
        Phone.objects.create(member=self.searcher, number='415-555-0101')
        self.do = Member.objects.create(
            username='dan duty', first_name='Dan', last_name='Duty', status='FM')
        Phone.objects.create(member=self.do, number='415-555-0102')

        now = timezone.now()
        self.event = Event.objects.create(
            type='operation', title='Test search', location='Somewhere',
            start_at=now, finish_at=now + timedelta(hours=4))
        self.period = self.event.period_set.first()
        self.period.participant_set.create(member=self.searcher)

        self.client.force_login(self.viewer)
        self.url = '/event/{}/'.format(self.event.id)

    def schedule_do(self, member):
        DoAvailable.objects.create(
            member=member, assigned=True, **DoAvailable.current_shift_dict())

    def test_no_scheduled_do(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['current_do'])
        self.assertContains(response, 'const CURRENT_DO = null;')
        self.assertContains(response, 'Copy ESB Spreadsheet details')

    def test_scheduled_do_not_attending(self):
        self.schedule_do(self.do)
        response = self.client.get(self.url)
        self.assertEqual(response.context['current_do'], self.do)
        self.assertContains(response, "name: 'Dan Duty'")
        self.assertContains(response, "id: '{}'".format(self.do.id))
        self.assertContains(response, r"phone: '415\u002D555\u002D0102'")
        self.assertRegex(response.content.decode(), r'<td>415-555-0101</td>\s*<td>false</td>')

    def test_scheduled_do_attending(self):
        self.schedule_do(self.searcher)
        response = self.client.get(self.url)
        self.assertRegex(response.content.decode(), r'<td>415-555-0101</td>\s*<td>true</td>')

    def test_esb_spreadsheet_url_from_preferences(self):
        response = self.client.get(self.url)
        self.assertContains(response, "const ESB_SPREADSHEET_URL = '';")

        global_preferences_registry.manager()['general__esb_spreadsheet_url'] = 'https://example.com/sheet'
        response = self.client.get(self.url)
        self.assertContains(response, "const ESB_SPREADSHEET_URL = 'https://example.com/sheet';")
