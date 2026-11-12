from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from main.models import Member, Phone, Role, Unavailable

from datetime import timedelta


class MemberTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = Member.objects.create(first_name='John',
                                          last_name='Doe',
                                          username='john doe',
                                          status='T',
        )

    def test_str(self):
        jd = Member.objects.get(first_name='John')
        full_name = str(jd)
        self.assertEqual(full_name, 'John Doe')

    def test_status_order(self):
        user_t = self.user
        user_fm = Member.objects.create(
                first_name='Jane',
                last_name='Smith',
                username='jane smith',
                status='FM',
        )
        user_tm = Member.objects.create(
                first_name='User',
                last_name='Three',
                username='user three',
                status='TM',
        )
        users = [user_t, user_tm, user_fm]
        users.sort(key=lambda x: x.status_order)
        self.assertEqual(users, [user_tm, user_fm, user_t])

    def test_role_order(self):
        user_t = self.user
        user_fm_ul_ol = Member.objects.create(
                first_name='Jane',
                last_name='Smith',
                username='jane smith',
                status='FM',
        )
        Role.objects.create(member=user_fm_ul_ol, role='UL')
        Role.objects.create(member=user_fm_ul_ol, role='OL')
        user_tm_xo = Member.objects.create(
                first_name='User',
                last_name='Three',
                username='user three',
                status='TM',
        )
        Role.objects.create(member=user_tm_xo, role='XO')
        users = [user_t, user_tm_xo, user_fm_ul_ol]
        users.sort(key=lambda x: x.role_order)
        self.assertEqual(users, [user_fm_ul_ol, user_tm_xo, user_t])

    def test_list_not_logged_in(self):
        response = self.client.get(reverse('member_list'))
        self.assertEqual(response.status_code, 302)
        
    def test_list_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('member_list'))
        self.assertEqual(response.status_code, 200)
        
    def test_detail_not_logged_in(self):
        response = self.client.get(self.user.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        
    def test_detail_logged_in(self):
        self.client.force_login(self.user)
        response = self.client.get(self.user.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_phone(self):
        phone = Phone.objects.create(
            member=self.user,
            number='1234567890'
        )
        self.assertEqual(phone.number, '+11234567890')
        self.assertEqual(phone.display_number, '123-456-7890')


class UnavailableTestCase(MemberTestCase):
    def setUp(self):
        super().setUp()
        today = timezone.now().date()
        Unavailable.objects.create(
            member=self.user,
            start_on=today + timedelta(days=-2),
            end_on=today,
        )
        Unavailable.objects.create(
            member=self.user,
            start_on=today + timedelta(days=2),
            end_on=today + timedelta(days=2),
        )
        Unavailable.objects.create(
            member=self.user,
            start_on=today + timedelta(days=4),
            end_on=today + timedelta(days=7),
        )
        Unavailable.objects.create(
            member=self.user,
            start_on=today + timedelta(days=10),
            end_on=today + timedelta(days=10),
        )

    def test_available_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('available_list'))
        self.assertEqual(response.status_code, 200)
