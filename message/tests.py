import json
import subprocess

from django.conf import settings
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

        # TODO test click on link


@override_settings(MESSAGE_FILE_PATH='/tmp/message_log',
                   DJANGO_TWILIO_FORGERY_PROTECTION=False)
class OutgoingSmsTestCase(TestCase):
    def setUp(self):
        self.number = '+15551234567'
        self.phone = mommy.make(Phone,
                                number=self.number,
                                make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       email=False,
                                       phone=True,
                                       make_m2m=True)
        self.c = Client()

    def test_send(self):
        self.distribution.message.send()

        f = settings.SMS_FILE_PATH + '/sms.log'
        proc = subprocess.Popen(['tail', '-n', '1', f], stdout=subprocess.PIPE)
        lines = proc.stdout.readlines()
        data = json.loads(lines[0].decode('utf-8'))

        self.assertEqual(data['to'], self.number)
        self.assertEqual(data['body'], self.distribution.message.text)

        sms = self.distribution.outboundsms_set.first()
        sms_id = sms.id
        self.assertEqual(sms.delivered, False)
        response = self.c.post(reverse('message:sms_callback'),
                               {'MessageSid': sms.sid,
                                'MessageStatus': 'delivered',
                                })
        self.assertEqual(response.status_code, 200)

        sms = OutboundSms.objects.get(id=sms_id)
        self.assertEqual(sms.delivered, True)

        # TODO Test SMS response
