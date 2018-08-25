from django.test import Client, TestCase
from django.urls import reverse
from main.models import Member

class MemberTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = Member.objects.create(first_name='John',
                                          last_name='Doe',
                                          username='john doe',
                                          member_rank='T',
        )

    def test_str(self):
        jd = Member.objects.get(first_name='John')
        full_name = str(jd)
        self.assertEqual(full_name, 'John Doe')

    def test_list_not_logged_in(self):
        response = self.client.get(reverse('member_index'))
        self.assertEqual(response.status_code, 302)
        
    def test_list_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('member_index'))
        self.assertEqual(response.status_code, 200)
        
    def test_detail_not_logged_in(self):
        response = self.client.get(self.user.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        
    def test_detail_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(self.user.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        
