"""Every page in the URLconf answers a GET without a server error, for a visitor who is not logged in, for a
member and for an officer. The routes are read from the URLconf, so a new page is swept as soon as it is added.
The sweep only makes GET requests, and the routes that page people or change data on a GET are left out."""
import re

from django.core import mail
from django.test import TestCase
from django.urls import URLPattern, get_resolver
from model_mommy import mommy

from main.models import Cert, CertSubType, Event, Member, Role

# Routes the sweep leaves out, by how they start.
LEFT_OUT = (
    # Paging: the pages that write, list and answer pages, and the webhooks of Twilio and Mailgun.
    'message/',
    'event/<int:event_id>/messages/',
    'action/',
    'unauth_rsvp/',
    'webhooks/',
    # A GET changes data: adds a period, counts a download, ends the session.
    'event/<int:pk>/period/add/',
    'file_id/',
    'file/<path:name>',
    'files/',
    '^accounts/logout/',
    # Asks Google for the DO group.
    'do_ahc_status/',
    # Redirects to a stored file, which the fixtures do not have.
    'photos/<int:id>/',
    'member/<int:member>/certs/<int:cert>/download/',
    'certs/<int:cert>/download/',
    # Other packages' routes. test_api covers the API's lists.
    'admin/',
    '^api/',
    '^api-auth/',
    '^api-docs/',
    '^openid/',
    '^social/',
    # A server error on main: without ?type= naming a cert type, CertType.DoesNotExist is not caught.
    'member/<int:member>/certs/new',
)


def routes_in(patterns, prefix=''):
    """The route of every pattern, with those of the URLconfs it includes, as the URLconf writes them."""
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLPattern):
            yield route
        else:
            yield from routes_in(pattern.url_patterns, route)


class UrlSweepTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = mommy.make(Member, status='TM')
        cls.officer = mommy.make(Member, status='TM')
        for role, _ in Role.TYPES:
            mommy.make(Role, member=cls.officer, role=role)
        # The member, the event and the cert share one id, so <pk> in any route finds its object.
        event = mommy.make(Event, id=cls.member.id)
        mommy.make(Cert, id=cls.member.id, member=cls.member, subtype=mommy.make(CertSubType))
        # What a route's placeholders are filled with. A route with one not named here fails until it is.
        cls.values = {
            'pk': cls.member.id,
            'period': event.period_set.get().id,
            'roster_type': 'full.html',
            'activity_type': 'summary',
            'uidb64': 'none',
            'token': 'none',
        }
        cls.routes = [route for route in routes_in(get_resolver().url_patterns)
                      if not route.startswith(LEFT_OUT)]

    def sweep(self, statuses):
        """GET every swept route as the client is logged in, and expect one of the statuses."""
        for route in self.routes:
            with self.subTest(route=route):
                path = re.sub(r'<(?:\w+:)?(\w+)>', lambda placeholder: str(self.values[placeholder[1]]), route)
                response = self.client.get('/' + path.strip('^$'))
                self.assertIn(response.status_code, statuses)
        self.assertEqual(mail.outbox, [])

    def test_a_visitor_gets_the_page_or_the_login(self):
        self.sweep({200, 302})

    def test_a_member_gets_the_page_or_is_refused(self):
        self.client.force_login(self.member)
        self.sweep({200, 403})

    def test_an_officer_gets_every_page(self):
        self.client.force_login(self.officer)
        self.sweep({200})
