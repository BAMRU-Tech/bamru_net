"""The member page's table of the last day of each type attended (counting.member_latest)."""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import Client
from django.urls import reverse

from main.lib.counting import (activity_rows, member_entries, member_latest, NotRun, operations_not_run,
                               operations_that_ran)
from main.models import Event, Participant, Period
from main.tests.helpers import NOW, ActivityTestCase, PageTestCase, when


class MemberLatestTestCase(ActivityTestCase):
    def make_event(self, event_type, start, *args, **kwargs):
        """As for every test; and an operation is called out for, with a callout page, as most are."""
        event = super().make_event(event_type, start, *args, **kwargs)
        if event_type == 'operation':
            self.paged(event, 'Available?')
        return event

    def test_no_events(self):
        self.make_event('training', when(2024, 3, 1), no_time=[self.member])
        self.assertEqual(member_latest(self.member, NOW), [])

    def test_latest(self):
        self.make_event('operation', when(2023, 1, 1), attended=[self.member])
        latest = self.make_event('operation', when(2024, 3, 20), attended=[self.member])
        self.make_event('operation', when(2024, 5, 1), attended=[self.other], no_time=[self.member])
        items = self.latest()
        self.assertEqual(list(items), ['Operation (in the field)', 'Training', 'Meeting', 'Community'])
        self.assertEqual(items['Operation (in the field)']['event'], latest)
        self.assertEqual(items['Operation (in the field)']['ago'], '2 months')
        self.assertIsNone(items['Meeting'].get('event'))

    def test_a_day_after_today_is_not_the_last(self):
        # A meeting in January with its times typed a year ahead, and a real one in May.
        slip = self.make_event('meeting', when(2024, 1, 10))
        Participant.objects.create(period=slip.period_set.first(), member=self.member,
                                   en_route_at=when(2025, 1, 10), return_home_at=when(2025, 1, 10) + timedelta(hours=2))
        self.assertEqual(member_latest(self.member, NOW), [])
        real = self.make_event('meeting', when(2024, 5, 10), attended=[self.member])
        meeting = self.latest()['Meeting']
        self.assertEqual((meeting['event'], meeting['day'], meeting['ago']), (real, date(2024, 5, 10), '1 month'))
        # A training under way: yesterday and today count, the days still to come do not.
        training = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=training.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 18))
        self.assertEqual(self.latest()['Training']['day'], date(2024, 6, 15))

    def test_ahc_shown_only_when_more_recent(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.member])
        self.assertNotIn('Operation (as AHC)', self.latest())
        ahc = self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        items = self.latest()
        self.assertEqual(items['Operation (as AHC)']['event'], ahc)
        self.assertEqual(items['Operation (in the field)']['day'], date(2024, 2, 10))

    def test_stood_down_shown_only_when_more_recent(self):
        self.make_event('operation', when(2024, 1, 10), no_time=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.member])
        self.assertNotIn('Operation (stood down)', self.latest())
        called_off = self.make_event('operation', when(2024, 4, 10), no_time=[self.member, self.other])
        self.assertEqual(self.latest()['Operation (stood down)']['event'], called_off)
        # A later AHC duty comes first, and hides it.
        self.make_event('operation', when(2024, 5, 10), attended=[self.other], ahc=[self.member])
        self.assertEqual([label for label in self.latest() if label.startswith('Operation')],
                         ['Operation (in the field)', 'Operation (as AHC)'])

    def test_ahc_time_on_a_called_off_operation_is_not_standing_down(self):
        # The AHC's time is the day before the operation's date.
        event = self.make_event('operation', when(2024, 3, 10), no_time=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 9), return_home_at=when(2024, 3, 9) + timedelta(hours=2))
        latest = self.latest()
        self.assertEqual(latest['Operation (as AHC)']['day'], date(2024, 3, 9))
        self.assertNotIn('Operation (stood down)', latest)

    def test_stood_down_only_from_an_operation_the_unit_was_called_out_for(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        # Nobody went out on any of these. Only a callout page ("Available?") makes standing down from one.
        unpaged = super().make_event       # an operation without the callout page this case gives the others
        heads_up = unpaged('operation', when(2024, 2, 10), no_time=[self.member])
        self.paged(heads_up, 'Heads Up')
        self.assertNotIn('Operation (stood down)', self.latest())
        silent = unpaged('operation', when(2024, 3, 10), no_time=[self.member])     # no page at all
        self.assertNotIn('Operation (stood down)', self.latest())
        called_out = unpaged('operation', when(2024, 1, 20), no_time=[self.member])
        self.paged(called_out, 'Heads Up')
        self.paged(called_out, 'Available?')
        self.assertEqual(self.latest()['Operation (stood down)']['event'], called_out)
        self.assertEqual(self.not_run(), {heads_up.id: 'heads_up', silent.id: 'heads_up', called_out.id: 'called_off'})

    def test_before_pages_had_reply_templates_an_operation_not_run_was_called_off(self):
        # Pages from before 13 February 2019 had no reply template, so a heads-up cannot be told from a callout.
        self.make_event('meeting', when(2018, 6, 10), attended=[self.member])
        before = super().make_event('operation', when(2019, 2, 12), no_time=[self.member])
        self.assertEqual(self.latest()['Operation (stood down)']['event'], before)
        after = super().make_event('operation', when(2019, 2, 13), no_time=[self.member])
        # 8pm on the 12th, Pacific time, though the 13th in UTC.
        evening = super().make_event('operation', datetime(2019, 2, 13, 4, 0, tzinfo=dt_timezone.utc), no_time=[self.member])
        ids = [before.id, after.id, evening.id]
        not_run = operations_not_run(NOW, operations_that_ran(NOW, ids), ids)
        self.assertEqual(not_run, {before.id: NotRun('called_off', date(2019, 2, 12)),
                                   after.id: NotRun('heads_up', date(2019, 2, 13)),
                                   evening.id: NotRun('called_off', date(2019, 2, 12))})

    def test_stood_down_from_one_operation_though_another_listed_on_ran(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], no_time=[self.member])     # ran
        called_off = self.make_event('operation', when(2024, 3, 10), no_time=[self.member, self.other])
        self.assertEqual(self.latest().get('Operation (stood down)', {}).get('event'), called_off)

    def test_stood_down_once_the_operation_has_finished(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        # Under way, with nobody's time logged yet: not called off.
        self.make_event('operation', NOW - timedelta(hours=2), no_time=[self.member, self.other], hours=24)
        self.assertNotIn('Operation (stood down)', self.latest())
        # Yesterday's, finished, with no time logged: called off at once.
        yesterday = self.make_event('operation', when(2024, 6, 14), no_time=[self.member, self.other])
        self.assertEqual(self.latest()['Operation (stood down)']['event'], yesterday)
        # One finishing at this very moment has finished.
        this_morning = self.make_event('operation', NOW - timedelta(hours=4), no_time=[self.member, self.other])
        self.assertEqual(self.latest()['Operation (stood down)']['event'], this_morning)

    def test_an_operation_ran_whatever_slips_were_made_in_its_times(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        # Someone else's time on it runs eight days, a slip: it still ran, and nobody stood down from it.
        slip = self.make_event('operation', when(2024, 3, 1), attended=[self.other], no_time=[self.member],
                               hours=24 * 8)
        self.assertNotIn('Operation (stood down)', self.latest())
        self.assertEqual(self.latest(self.other)['Operation (in the field)']['event'], slip)

    def test_ahc_on_a_called_off_operation_is_duty_and_the_listed_stood_down(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member, self.other])
        called_off = self.make_event('operation', when(2024, 3, 10), ahc=[self.member], no_time=[self.other])
        latest = self.latest()
        self.assertEqual(latest['Operation (as AHC)']['event'], called_off)
        self.assertNotIn('Operation (stood down)', latest)
        self.assertEqual(self.latest(self.other)['Operation (stood down)']['event'], called_off)

    def test_an_operation_whose_only_time_is_after_today_did_not_run(self):
        # As on both reports: time for a day after today is left out, so nobody went yet.
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        called_off = self.make_event('operation', when(2024, 3, 1), no_time=[self.member])
        Participant.objects.create(period=called_off.period_set.first(), member=self.other,
                                   en_route_at=when(2025, 3, 1), return_home_at=when(2025, 3, 1) + timedelta(hours=4))
        self.assertEqual(self.latest()['Operation (stood down)']['event'], called_off)
        self.assertEqual(operations_that_ran(NOW, [called_off.id]), set())
        self.assertEqual(self.years()['2024'].unit_events['operation'], 0)

    def test_an_operation_ran_by_the_local_day_its_time_falls_on(self):
        # Attended only today, from 7am Pacific: it ran.
        today = self.make_event('operation', when(2024, 6, 15) - timedelta(hours=6), attended=[self.other])
        self.assertEqual(operations_that_ran(NOW, [today.id]), {today.id})
        # At 03:00 UTC on the 15th it is the evening of the 14th in Pacific time, so time logged
        # after midnight Pacific has not come yet, though its UTC date has.
        evening = datetime(2024, 6, 15, 3, 0, tzinfo=dt_timezone.utc)
        late = self.make_event('operation', when(2024, 6, 14))
        Participant.objects.create(period=late.period_set.first(), member=self.other,
                                   en_route_at=datetime(2024, 6, 15, 7, 30, tzinfo=dt_timezone.utc),
                                   return_home_at=datetime(2024, 6, 15, 9, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(operations_that_ran(evening, [late.id]), set())

    def test_a_member_whose_only_time_on_an_operation_is_after_today_stood_down(self):
        # Time dated after today counts nothing yet, so the member was listed on an operation nobody went out on.
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        operation = self.make_event('operation', when(2024, 3, 10))
        Participant.objects.create(period=operation.period_set.first(), member=self.member,
                                   en_route_at=when(2025, 3, 10), return_home_at=when(2025, 3, 10) + timedelta(hours=4))
        self.assertEqual(self.latest()['Operation (stood down)']['event'], operation)

    def test_an_operation_only_a_guest_logged_time_on_did_not_run(self):
        guest = self.make_member('Gus', 'G')
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 4, 20), attended=[guest], no_time=[self.member])
        self.assertIn('Operation (stood down)', self.latest())

    def test_the_unit_is_asked_only_about_operations_that_may_have_been_called_off(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='Ann (TL)')
        self.make_event('operation', when(2024, 2, 10), attended=[self.member, self.other])
        # The member's entries, and nothing else: no usernames for who led, no look at the unit.
        with self.assertNumQueries(1):
            member_latest(self.member, NOW)
        # Listed without time on an operation that has finished: one more, about that operation.
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], no_time=[self.member])
        with self.assertNumQueries(2):
            self.assertNotIn('Operation (stood down)', self.latest())
        # One still under way is not asked about.
        self.make_event('operation', NOW - timedelta(hours=2), no_time=[self.member], hours=24)
        with self.assertNumQueries(2):
            member_latest(self.member, NOW)

    def test_listed_without_time_on_one_period_of_an_operation_timed_on_another_is_not_standing_down(self):
        operation = self.make_event('operation', when(2024, 3, 10), no_time=[self.member])
        second = Period.objects.create(event=operation, position=2)
        Participant.objects.create(period=second, member=self.member,
                                   en_route_at=when(2024, 3, 11), return_home_at=when(2024, 3, 11) + timedelta(hours=4))
        latest = self.latest()
        self.assertNotIn('Operation (stood down)', latest)
        self.assertEqual(latest['Operation (in the field)']['event'], operation)
        # The same when that time was as AHC, the day before the operation's date: AHC duty, not standing down.
        ahc = self.make_event('operation', when(2024, 4, 10), no_time=[self.member])
        Participant.objects.create(period=Period.objects.create(event=ahc, position=2), member=self.member, ahc=True,
                                   en_route_at=when(2024, 4, 9), return_home_at=when(2024, 4, 9) + timedelta(hours=2))
        latest = self.latest()
        self.assertNotIn('Operation (stood down)', latest)
        self.assertEqual(latest['Operation (as AHC)']['event'], ahc)

    def test_a_line_on_the_same_day_as_one_above_it_is_not_shown(self):
        self.make_event('operation', when(2024, 3, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        self.assertNotIn('Operation (as AHC)', self.latest())
        self.make_event('operation', when(2024, 3, 10), no_time=[self.member])     # called off the same day
        self.assertNotIn('Operation (stood down)', self.latest())

    def test_an_operation_stood_down_from_is_placed_on_the_day_it_started(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), no_time=[self.member], hours=60)   # finished on the 13th
        self.assertEqual(self.latest()['Operation (stood down)']['day'], date(2024, 3, 10))

    def test_today_on_the_member_page_is_the_local_day(self):
        # 03:00 UTC on 15 June is the evening of the 14th in Pacific time: time on the 15th has not come.
        evening = datetime(2024, 6, 15, 3, 0, tzinfo=dt_timezone.utc)
        self.make_event('training', when(2024, 6, 14), attended=[self.member])         # the afternoon of the 14th
        ahead = self.make_event('training', when(2024, 6, 14) + timedelta(hours=1))
        Participant.objects.create(period=ahead.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 15), return_home_at=when(2024, 6, 15) + timedelta(hours=4))
        self.make_event('meeting', when(2024, 5, 15), attended=[self.member])
        latest = {i['label']: i for i in member_latest(self.member, evening)}
        self.assertEqual(latest['Training']['day'], date(2024, 6, 14))
        # And how long ago is counted to the 14th: the 15th of May is not yet a month ago.
        self.assertEqual(latest['Meeting']['ago'], 'Under a month')

    def test_how_long_ago_is_in_years_from_two(self):
        two, under = self.make_member('Two', 'FM'), self.make_member('Under', 'FM')
        self.make_event('meeting', when(2022, 6, 15), attended=[two])
        self.make_event('meeting', when(2022, 6, 16), attended=[under])
        self.assertEqual((self.latest(two)['Meeting']['ago'], self.latest(under)['Meeting']['ago']),
                         ('2 years', '23 months'))

    def test_how_long_ago(self):
        self.make_event('operation', when(2021, 11, 10), attended=[self.member])    # 31 months
        self.make_event('training', when(2023, 5, 20), attended=[self.member])      # 12 months and some days
        self.make_event('meeting', when(2024, 6, 10), attended=[self.member])
        self.make_event('community', when(2024, 5, 10), attended=[self.member])
        self.assertEqual([i['ago'] for i in member_latest(self.member, NOW)],
                         ['2 years', '12 months', 'Under a month', '1 month'])

    def test_matches_the_report(self):
        # The member page looks only at the member's own operations; the dates
        # must be the ones the report would count.
        self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member], hours=30)
        self.make_event('training', when(2024, 2, 10), attended=[self.member], hours=30)
        self.assertEqual(activity_rows(self.member, NOW, member_entries(self.member))['total'].ahc_days, 1)
        items = self.latest()
        self.assertEqual(items['Operation (as AHC)']['day'], date(2024, 1, 10))
        self.assertEqual(items['Training']['day'], date(2024, 2, 11))


class MemberPageTestCase(PageTestCase):
    def test_member_page_table(self):
        event = self.make_event('operation', when(2024, 1, 10), attended=[self.member, self.other])
        Event.objects.filter(pk=event.pk).update(title='<b>Search</b>')
        client = Client()
        client.force_login(self.other)
        response = client.get(self.member.get_absolute_url())
        # A line with its event linked, its title escaped, its day and how long ago; one with none, its cells blank.
        link = reverse('event_detail', args=[event.id])
        self.assertContains(response, '<tr><td>Operation (in the field)</td><td><a href="{}">&lt;b&gt;Search&lt;/b&gt;</a>'
                            '</td><td>10 Jan 2024</td><td>5 months</td></tr>'.format(link),
                            html=True)
        self.assertContains(response, '<tr><td>Training</td><td>None</td><td></td><td></td></tr>', html=True)

