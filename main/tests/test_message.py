import json
import os
import re
import subprocess
import unittest

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from dynamic_preferences.registries import global_preferences_registry
from model_mommy import mommy

from main.models import *
from main.tasks import *

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
                                       send_email=True,
                                       send_sms=False,
                                       make_m2m=True)
        self.c = Client()

    def follow_link(self, html, index):
        url = re.findall('href="([^"]+)"', html)[index]
        relative = re.search('{}(/.*)'.format(settings.HOSTNAME), url).group(1)

        # Respond to page
        response = self.c.get(relative)
        self.assertEqual(response.status_code, 200)
        return relative

    @unittest.skipUnless(settings.ANYMAIL['MAILGUN_API_KEY'], 'missing config')
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
        url_yes = self.follow_link(html, 0)
        url_no = self.follow_link(html, 1)

        # The button on that page would POST yes
        response = self.c.post(url_yes, {'rsvp': 'yes'})
        self.assertEqual(response.status_code, 200)

        # Check that member is added to the event
        self.assertTrue(Participant.objects.filter(
            member=self.email.member,
            period=self.period).exists())

        # POST no
        response = self.c.post(url_no, {'rsvp': 'no'})
        self.assertEqual(response.status_code, 200)

        # Check that member is removed from the event
        self.assertFalse(Participant.objects.filter(
            member=self.email.member,
            period=self.period).exists())


@override_settings(SMS_FILE_PATH='/tmp',
                   TWILIO_SMS_FROM=['+15005550006'],
                   DJANGO_TWILIO_FORGERY_PROTECTION=False)
class OutgoingSmsTestCase(TestCase):
    def setUp(self):
        self.number = '+15551234567'
        self.phone = mommy.make(Phone,
                                number=self.number,
                                make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       send_email=False,
                                       send_sms=True,
                                       make_m2m=True)
        self.c = Client()

    @unittest.skipUnless(settings.ANYMAIL['MAILGUN_API_KEY'], 'missing config')
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
        response = self.c.post(reverse('sms_callback'),
                               {'MessageSid': sms.sid,
                                'MessageStatus': 'delivered',
                                })
        self.assertEqual(response.status_code, 200)

        # Make sure it's now marked as delivered
        sms = OutboundSms.objects.get(id=sms_id)
        self.assertEqual(sms.delivered, True)


@override_settings(SMS_FILE_PATH='/tmp',
                   EMAIL_BACKEND='anymail.backends.test.EmailBackend',
                   TWILIO_SMS_FROM=['+15005550006'],
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
        self.rsvp = mommy.make(RsvpTemplate)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       message__period=self.participant.period,
                                       message__format='page',
                                       message__period_format='leave',
                                       message__rsvp_template=self.rsvp,
                                       send_email=False,
                                       send_sms=True,
                                       make_m2m=True)
        self.c = Client()
        self.global_preferences = global_preferences_registry.manager()
        self.global_preferences['google__do_group'] = 'do@example.com'

    @unittest.skipUnless(settings.ANYMAIL['MAILGUN_API_KEY'], 'missing config')
    def test_send(self):
        # Send a transit page
        self.distribution.message.queue()
        message_send(0)
        source = self.distribution.outboundsms_set.first().source

        #####
        # First response doesn't match yes/no check
        body = 'unmatched'
        response = self.c.post(reverse('sms'),
                               {'To': source,
                                'From': self.number,
                                'MessageSid': 'FAKE_SID_SMS',
                                'Body': body,
                                })
        self.assertEqual(response.status_code, 200)

        # Test that one message was sent:
        self.assertEqual(len(mail.outbox), 1)

        msg = mail.outbox[0]
        self.assertEquals(self.global_preferences['google__do_group'], msg.to[0])
        self.assertIn(body, msg.body)
        self.assertIn(str(self.number), msg.body)

        # Check no RSVP recorded
        self.assertIsNone(self.participant.en_route_at)

        #####
        # Respond Yes to page
        response = self.c.post(reverse('sms'),
                               {'To': source,
                                'From': self.number,
                                'MessageSid': 'FAKE_SID_SMS',
                                'Body': 'Yes',
                                })
        self.assertEqual(response.status_code, 200)

        # Check that RSVP is now there
        p2 = Participant.objects.get(pk=self.participant.id)
        self.assertIsNotNone(p2.en_route_at)

    def test_extra_info(self):
        self.assertFalse(InboundSms.has_extra_info('y'))
        self.assertFalse(InboundSms.has_extra_info('yes.'))
        self.assertFalse(InboundSms.has_extra_info('yea'))
        self.assertFalse(InboundSms.has_extra_info('yeah'))
        self.assertFalse(InboundSms.has_extra_info('yep '))
        self.assertFalse(InboundSms.has_extra_info('Yes 👍 ')) # emoji

        self.assertFalse(InboundSms.has_extra_info('N'))
        self.assertFalse(InboundSms.has_extra_info('N   '))
        self.assertFalse(InboundSms.has_extra_info('No.'))
        self.assertFalse(InboundSms.has_extra_info('Nope'))

        self.assertTrue(InboundSms.has_extra_info('No x'))
        self.assertTrue(InboundSms.has_extra_info('Not yet'))
        self.assertTrue(InboundSms.has_extra_info('Ok'))
        self.assertTrue(InboundSms.has_extra_info('on'))



@override_settings(TWILIO_SMS_FROM=['+15005550006'])
class OutgoingSmsTwilioTestCase(TestCase):
    def send_number_expect_code(self, number, code):
        self.number = number
        self.phone = mommy.make(Phone,
                                number=self.number,
                                make_m2m=True)
        self.distribution = mommy.make(Distribution,
                                       member=self.phone.member,
                                       send_email=False,
                                       send_sms=True,
                                       make_m2m=True)
        self.distribution.message.queue()
        message_send(0)
        self.sms = self.distribution.outboundsms_set.first()
        self.assertEqual(self.sms.error_code, code)

    @unittest.skipUnless(os.environ['TWILIO_TEST_AUTH_TOKEN'], 'missing config')
    def test_send(self):
        old_path = settings.SMS_FILE_PATH
        settings.SMS_FILE_PATH = None
        # We need to override the client setting, but it is set up at
        # module load. Thus we need to overide the created
        # twilio_clent object.
        from django_twilio import client
        from twilio.rest import Client
        client.twilio_client = Client(os.environ['TWILIO_TEST_ACCOUNT_SID'],
                                      os.environ['TWILIO_TEST_AUTH_TOKEN'])

        self.send_number_expect_code('+15005550001', 21211) # invalid #
        self.send_number_expect_code('+15005550009', 21614) # incapable
        self.send_number_expect_code('+14058675309', None)  # Success

        settings.SMS_FILE_PATH = old_path
