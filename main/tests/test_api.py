from rest_framework.test import APIClient, APITestCase
from main.models import Member, MemberStatusType

class TestApiRoot(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.uri = '/api/'
        self.user = Member.objects.create(first_name='John',
                                          last_name='Doe',
                                          username='john doe',
                                          status=MemberStatusType.objects.first(),
        )

    def test_access(self):
        self.client.force_login(self.user)
        response = self.client.get(self.uri)
        self.assertEqual(response.status_code, 200)
        self.client.logout()
        for endpoint in response.json().values():
            response = self.client.get(endpoint)
            self.assertEqual(
                response.status_code, 403,
                'Expected 403 forbidden because we are not logged in')

    def test_lists(self):
        self.client.force_login(self.user)
        response = self.client.get(self.uri)
        self.assertEqual(response.status_code, 200)
        for endpoint in response.json().values():
            response = self.client.get(endpoint)
            self.assertEqual(
                response.status_code, 200,
                'Expected 200 OK because we are logged in')

    def test_filters(self):
        self.client.force_login(self.user)
        response = self.client.get(self.uri)
        self.assertEqual(response.status_code, 200)
        response = self.client.get(self.uri + 'members/?status=TM')
        self.assertEqual(response.status_code, 200)
        response = self.client.get(self.uri + 'member_availability/?status=TM')
        self.assertEqual(response.status_code, 200)
