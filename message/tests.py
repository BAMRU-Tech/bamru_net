import json
import os
import re
import subprocess

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase
from django.test.utils import override_settings
from model_mommy import mommy

from main.models import Email, Participant

from .models import *
from .tasks import *

@override_settings(EMAIL_BACKEND='anymail.backends.test.EmailBackend')
class OutgoingEmailTestCase(TestCase):
    def setUp(self):
        self.address = 'message_test@example.com'
        self.email = mommy.make(Email,
                                address=self.address,
                                make_m2m=True)
        self.period = mommy.make(Period,
                                 make_m2m=True)
        self.rsvp_template = mommy.make(RsvpTemplate)
        self.distribution = mommy.make(Distribution,
                                       member=self.email.member,
                                       message__period=self.period,
                                       message__format='page',
                                       message__period_format='invite',
                                       message__rsvp_template=self.rsvp_template,
                                       email=True,
                                       phone=False,
                                       make_m2m=True)
        self.c = Client()

    def follow_link(self, html, index):
        url = re.findall('href="([^"]+)"', html)[index]
        relative = re.search('{}(/.*)'.format(settings.HOSTNAME), url).group(1)

        # Respond to page
        response = self.c.get(relative)
        self.assertEqual(response.status_code, 200)

    def test_send(self):
        self.distribution.message.queue()
        message_send(0)

        # Test that one message was sent:
        self.assertEqual(len(mail.outbox), 1)

        msg = mail.outbox[0]
        self.assertEqual(msg.to, [self.address])

        # Extract the html part
        html = msg.alternatives[0][0]

        # Second link should be No and have no effect
        self.follow_link(html, 1)
        self.assertFalse(Participant.objects.filter(
            member=self.email.member,
            period=self.period).exists())

        # First link should be Yes
        self.follow_link(html, 0)

        # Check that member is added to the event
        self.assertTrue(Participant.objects.filter(
            member=self.email.member,
            period=self.period).exists())

        # Second link should be No
        self.follow_link(html, 1)

        # Check that member is removed from the event
        self.assertFalse(Participant.objects.filter(
            member=self.email.member,
            period=self.period).exists())


@override_settings(SMS_FILE_PATH='/tmp',
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
        # Send a generic page
        self.distribution.message.queue()
        message_send(0)

        # Check that it is logged
        f = settings.SMS_FILE_PATH + '/sms.log'
        proc = subprocess.Popen(['tail', '-n', '1', f], stdout=subprocess.PIPE)
        lines = proc.stdout.readlines()
        data = json.loads(lines[0].decode('utf-8'))

        self.assertEqual(data['to'], self.number)
        self.assertEqual(data['body'], self.distribution.message.text)

        # Emulate a status callback
        sms = self.distribution.outboundsms_set.first()
        sms_id = sms.id
        self.assertEqual(sms.delivered, False)
        response = self.c.post(reverse('message:sms_callback'),
                               {'MessageSid': sms.sid,
                                'MessageStatus': 'delivered',
                                })
        self.assertEqual(response.status_code, 200)

        # Make sure it's now marked as delivered
        sms = OutboundSms.objects.get(id=sms_id)
        self.assertEqual(sms.delivered, True)


@override_settings(SMS_FILE_PATH='/tmp',
                   DJANGO_TWILIO_FORGERY_PROTECTION=False)
class IncommingSmsTestCase(TestCase):
    def setUp(self):
        self.number = '+15552345678'
        self.phone = mommy.make(Phone,
                                number=self.number,
                                make_m2m=True)
        self.participant = mommy.make(Participant,
                                      member=self.phone.member,
                                      make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       message__period=self.participant.period,
                                       message__format='page',
                                       message__period_format='leave',
                                       email=False,
                                       phone=True,
                                       make_m2m=True)
        self.c = Client()

    def test_send(self):
        # Send a transit page
        self.distribution.message.queue()
        message_send(0)

        # Check no RSVP before
        self.assertIsNone(self.participant.en_route_at)

        # Respond Yes to page
        response = self.c.post(reverse('message:sms'),
                               {'To': '+5550123456',
                                'From': self.number,
                                'MessageSid': 'FAKE_SID_SMS',
                                'Body': 'Yes',
                                })
        self.assertEqual(response.status_code, 200)

        # Check that RSVP is now there
        p2 = Participant.objects.get(pk=self.participant.id)
        self.assertIsNotNone(p2.en_route_at)



@override_settings(TWILIO_SMS_FROM='+15005550006')
class OutgoingSmsTwilioTestCase(TestCase):
    def send_number_expect_code(self, number, code):
        self.number = number
        self.phone = mommy.make(Phone,
                                number=self.number,
                                make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       email=False,
                                       phone=True,
                                       make_m2m=True)
        self.distribution.message.queue()
        message_send(0)
        self.sms = self.distribution.outboundsms_set.first()
        self.assertEqual(self.sms.error_code, code)

    def test_send(self):
        # We need to override the client setting, but it is set up at
        # module load. Thus we need to overide the created
        # twilio_clent object.
        from django_twilio import client
        from twilio.rest import Client
        client.twilio_client = Client(os.environ['TWILIO_TEST_ACCOUNT_SID'],
                                      os.environ['TWILIO_TEST_AUTH_TOKEN'])

        self.send_number_expect_code('+15550000001', 21211) # invalid #
        self.send_number_expect_code('+15550000009', 21614) # incapable
        self.send_number_expect_code('+14058675309', None)  # Success
