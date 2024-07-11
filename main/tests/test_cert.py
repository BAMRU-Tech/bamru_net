from datetime import timedelta
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from main.models import Cert, CertType, CertSubType
from main.tests.test_member import MemberTestCase

class CertTestCase(MemberTestCase):
    def setUp(self):
        super().setUp()
        today = timezone.now().date()
        med = CertType.objects.get_or_create(name='Medical')[0]
        self.med_wfr = CertSubType.objects.get_or_create(type=med, name='WFR')[0]
        cpr = CertType.objects.get_or_create(name='CPR')[0]
        cpr_a = CertSubType.objects.get_or_create(type=cpr, name='A')[0]
        ham = CertType.objects.get_or_create(name='HAM')[0]
        ham_other = CertSubType.objects.get_or_create(
            type=ham, name='HAM', is_other=True)[0]
        self.cert = Cert.objects.create(
            member=self.user,
            subtype=self.med_wfr,
            expires_on=today + timedelta(days=100),
        )
        Cert.objects.create(
            member=self.user,
            subtype=cpr_a,
            expires_on=today + timedelta(days=50),
        )
        Cert.objects.create(
            member=self.user,
            subtype=ham_other,
            description='K0TEST',
            expires_on=today + timedelta(days=10),
        )

    def test_cert_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('cert_list'))
        self.assertEqual(response.status_code, 200)

    def test_member_cert_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('member_cert_list', args=[self.user.id]))
        self.assertEqual(response.status_code, 200)

    def test_new_cert(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('member_cert_new', args=[self.user.id]) + '?type=Medical')
        self.assertEqual(response.status_code, 200)

        orig_num_certs = Cert.objects.filter(member=self.user).count()

        response = self.client.post(reverse('member_cert_new', args=[self.user.id]) + '?type=Medical', {
            'subtype': self.med_wfr.id,
            'expires_on': '2018-12-31',
            'comment': 'w',
        })
        self.assertEqual(response.status_code, 302)

        new_num_certs = Cert.objects.filter(member=self.user).count()
        self.assertEqual(orig_num_certs + 1, new_num_certs)
