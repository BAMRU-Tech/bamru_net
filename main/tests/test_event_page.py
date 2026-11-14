"""Leaders on the event page, and the members each leaders text names for the reports."""
from django.test import Client
from django.urls import reverse

from main.lib.counting import activity_rows
from main.models import Event
from main.models.event import leader_parts, members_named
from main.tests.helpers import NOW, ActivityTestCase, when


class EventLeadersTestCase(ActivityTestCase):
    def named(self, text, *usernames):
        """Those of these usernames a leaders text names, by members_named."""
        return members_named([text], [(username, username) for username in usernames]).get(text, set())

    def test_members_named(self):
        text = 'Ann  Lee (TL), bo diaz and CY NG(LL) / Search and Rescue Team'
        for username in ('ann lee', 'Ann Lee', 'bo diaz', 'cy ng', ' cy  ng ', 'lee', 'team'):
            self.assertEqual(self.named(text, username), {username}, username)
        # Whole words only, and never an empty username.
        for username in ('ann le', 'o diaz', 'sue lee', 'tea', '', ' '):
            self.assertEqual(self.named(text, username), set(), username)
        self.assertEqual(members_named([None, ''], [('ann lee', 1)]), {})
        # Punctuation in a username is matched as written.
        self.assertEqual(self.named("Pat O'Neil-Diaz (TL)", "pat o'neil-diaz"), {"pat o'neil-diaz"})
        self.assertEqual(self.named('Pat O.Neil', "pat o'neil"), set())
        # Many texts are read with one pattern.
        self.assertEqual(members_named(['Ann Lee (TL)', 'Bo Diaz, Ann Lee', 'nobody'], [('ann lee', 1), ('bo diaz', 2)]),
                         {'Ann Lee (TL)': {1}, 'Bo Diaz, Ann Lee': {1, 2}, 'nobody': set()})

    def test_the_event_page_reads_a_text_as_the_reports_do(self):
        # Ignoring case, Python's patterns take a long s for an s and a micro sign for a mu, where lower() does
        # not; read one way, "ſam fox" is matched whole, not linked, and leaves no "fox" for member 2.
        members = [('sam fox', 1), ('fox', 2), ('μike lee', 3), ('lee', 4)]
        for text in ('ſam fox (TL)', 'µike lee (LL)'):
            linked = {id for _, id in leader_parts(text, members) if id}
            self.assertEqual(linked, members_named([text], members)[text], text)
            self.assertEqual(linked, set(), text)

    def test_an_underscore_ends_a_username(self):
        self.assertEqual(self.named('ann_lee (TL)', 'ann'), {'ann'})

    def test_a_former_member_named_as_a_leader_is_linked_and_credited(self):
        # Whatever their status today, so that past years keep who led them.
        alum = self.make_member('Cat', 'MA')
        event = self.make_event('training', when(2024, 1, 10), attended=[alum, self.other], leaders='Cat (TL)')
        self.assertEqual(Event.members_named(['Cat (TL)']), {'Cat (TL)': {alum.id}})
        client = Client()
        client.force_login(self.other)
        self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                            '<a href="{}">Cat</a> (TL)'.format(alum.get_absolute_url()))
        self.assertEqual(activity_rows(alum, NOW)['total'].led_events['training'], 1)

    def test_the_longer_username_is_the_one_named(self):
        # Longer by its letters, not its words.
        self.assertEqual(self.named('Ann Lee-Fox (TL)', 'ann lee', 'ann lee-fox'), {'ann lee-fox'})
        # Where two usernames could match at one place, the longer is the one named.
        self.assertEqual(self.named('Ann Lee (TL)', 'lee'), {'lee'})
        self.assertEqual(self.named('Ann Lee (TL)', 'lee', 'ann lee', 'ann'), {'ann lee'})
        # A username ends at a hyphen or an apostrophe too, so one inside another's word is not named.
        self.assertEqual(self.named("Pat O'Neil-Diaz (TL)", 'diaz', "pat o'neil-diaz"), {"pat o'neil-diaz"})
        self.assertEqual(leader_parts("Pat O'Neil-Diaz (TL)", [("pat o'neil-diaz", 1), ('diaz', 2)]),
                         [("Pat O'Neil-Diaz", 1), (' (TL)', None)])
        # Named in its own right elsewhere in the text, the shorter still counts.
        self.assertEqual(self.named('Ann Lee (TL), Lee (LL)', 'lee', 'ann lee'), {'lee', 'ann lee'})
        self.assertEqual(self.named('Lee Fox', 'lee fox', 'lee'), {'lee fox'})

    def test_leader_parts(self):
        text = 'Ann Lee (TL), bo diaz and Ann Leeson'
        members = [('ann lee', 1), ('bo diaz', 2), ('ann leeson', 3), ('ann', 4), ('cy ng', 5)]
        self.assertEqual(leader_parts(text, members), [
            ('Ann Lee', 1), (' (TL), ', None), ('bo diaz', 2), (' and ', None), ('Ann Leeson', 3)])
        self.assertEqual(leader_parts(text, []), [('Ann Lee (TL), bo diaz and Ann Leeson', None)])
        # The first username to start in the text wins, before the longer one.
        self.assertEqual(leader_parts('Ann Lee Fox', [('ann lee', 1), ('lee fox', 2)]), [('Ann Lee', 1), (' Fox', None)])
        self.assertEqual(self.named('Ann Lee Fox', 'ann lee', 'lee fox'), {'ann lee'})
        # Of two usernames that differ only by case or spacing, the first given.
        self.assertEqual(leader_parts('Ann Lee', [('Ann  Lee', 7), ('ann lee', 8)]), [('Ann Lee', 7)])
        self.assertEqual(leader_parts('', members), [])
        # A letter that matches in any case without lowering to the username stays plain text.
        self.assertEqual(leader_parts('\u017fam fox', [('sam fox', 6)]), [('\u017fam fox', None)])

    def test_event_page_links_each_leader(self):
        event = self.make_event('training', when(2024, 1, 10), leaders='Ann (TL) and BOB (LL), Someone <Else>')
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('event_detail', args=[event.id]))
        self.assertContains(response, '<a href="{}">Ann</a> (TL) and <a href="{}">BOB</a> (LL), Someone &lt;Else&gt;'
                            .format(self.member.get_absolute_url(), self.other.get_absolute_url()))
        # A username of two words is linked however the words are spaced.
        self.other.username = 'bob fox'
        self.other.save()
        event.leaders = 'Bob  Fox'
        event.save()
        self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                            '<a href="{}">Bob  Fox</a>'.format(self.other.get_absolute_url()))
        # However the username is stored, capitals, odd spacing and accents
        # included, the page links what Event.members_named says the text names.
        for stored, leaders in (('Bob  Fox', 'bob fox (TL)'), (' bob fox', 'BOB FOX'), ('\u00e9lan roy', '\u00c9LAN ROY (TL)')):
            self.other.username = stored
            self.other.save()
            event.leaders = leaders
            event.save()
            self.assertEqual(self.named(leaders, stored), {stored}, stored)
            self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                                '<a href="{}">'.format(self.other.get_absolute_url()), msg_prefix=stored)
        # Usernames between commas, as the page linked them before, still link.
        self.other.username = 'bob fox'
        self.other.save()
        event.leaders = 'ann, bob fox'
        event.save()
        self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                            '<a href="{}">ann</a>, <a href="{}">bob fox</a>'
                            .format(self.member.get_absolute_url(), self.other.get_absolute_url()))
        # A linked name is escaped like the rest of the text.
        self.other.username = 'a&b'
        self.other.save()
        event.leaders = 'A&B (TL)'
        event.save()
        self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                            '<a href="{}">A&amp;B</a> (TL)'.format(self.other.get_absolute_url()))
        # No leaders text is TBD; an empty one is shown empty, as before.
        event.leaders = None
        event.save()
        self.assertContains(client.get(reverse('event_detail', args=[event.id])), 'TBD')
        event.leaders = ''
        event.save()
        self.assertNotContains(client.get(reverse('event_detail', args=[event.id])), 'TBD')


    def test_of_two_usernames_alike_the_member_with_the_lower_id_leads_everywhere(self):
        self.member.username = 'Ann  Lee'
        self.member.save()
        self.other.username = 'ann lee'
        self.other.save()
        event = self.make_event('training', when(2024, 1, 10), attended=[self.member, self.other], leaders='Ann Lee (TL)')
        self.assertEqual(Event.members_named(['Ann Lee (TL)']), {'Ann Lee (TL)': {self.member.id}})
        client = Client()
        client.force_login(self.other)
        self.assertContains(client.get(reverse('event_detail', args=[event.id])),
                            '<a href="{}">Ann Lee</a> (TL)'.format(self.member.get_absolute_url()))
        led = {m: activity_rows(m, NOW)['total'].led_events['training'] for m in (self.member, self.other)}
        self.assertEqual(led, {self.member: 1, self.other: 0})
