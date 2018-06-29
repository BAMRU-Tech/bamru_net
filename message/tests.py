from django.core import mail
from django.test import Client, TestCase
from django.test.utils import override_settings
from model_mommy import mommy

from bnet.models import Email

from .models import *


@override_settings(EMAIL_BACKEND='anymail.backends.test.EmailBackend')
class OutgoingEmailTestCase(TestCase):
    def setUp(self):
        self.address = 'message_test@example.com'
        self.email = mommy.make(Email,
                                address=self.address,
                                make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.email.member,
                                       email=True,
                                       phone=False,
                                       make_m2m=True)

    def test_send(self):
        self.distribution.message.send()

        # Test that one message was sent:
        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(mail.outbox[0].to, [self.address])
