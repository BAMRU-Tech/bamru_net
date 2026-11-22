"""The member page's table of the last day of each type attended (counting.member_latest)."""
import time
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock, skipIf, skipUnless

from django.core.cache import cache, caches
from django.core.cache.backends.db import BaseDatabaseCache
from django.db import connection
from django.db.models.expressions import RawSQL
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from main.lib.counting import (NotRun, activity_rows, departure_entries, joined_on, member_entries, member_latest,
                               months_after, operations_not_run, operations_that_ran, records_from,
                               reply_templates_from)
from main.lib.unit_counting import unit_rows
from main.models import Address, EmergencyContact, Event, Participant, Period, Phone
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
        self.assertEqual(list(items), ['Operation (in the field)', 'Training (as participant)', 'Meeting', 'Community'])
        self.assertEqual(items['Operation (in the field)']['event'], latest)
        self.assertEqual(items['Operation (in the field)']['ago'], '3 months')         # 2 months and 26 days
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
        self.assertEqual(self.latest()['Training (as participant)']['day'], date(2024, 6, 15))

    def test_the_last_operation_as_ol_is_a_line_of_its_own(self):
        # Never OL: no line.
        self.make_event('operation', when(2024, 2, 10), attended=[self.member])
        self.assertNotIn('Operation (as OL)', self.latest())
        # In the field as OL in January, then in the field in February: the OL line, under the in-the-field one,
        # with its own event, day and how long ago, from the member's entries alone.
        led = self.make_event('operation', when(2024, 1, 10), ol=[self.member])
        with self.assertNumQueries(2):
            items = {i['label']: i for i in member_latest(self.member, NOW)}
        self.assertEqual(list(items), ['Operation (in the field)', 'Operation (as OL)', 'Training (as participant)', 'Meeting',
                                       'Community'])
        self.assertEqual((items['Operation (as OL)']['event'], items['Operation (as OL)']['day'],
                          items['Operation (as OL)']['ago']), (led, date(2024, 1, 10), '5 months'))
        self.assertEqual(items['Operation (in the field)']['day'], date(2024, 2, 10))
        # As OL on the latest operation too: both lines, alike, so the table says when they last led without the
        # reader comparing lines.
        latest = self.make_event('operation', when(2024, 3, 10), ol=[self.member])
        items = self.latest()
        self.assertEqual((items['Operation (as OL)']['event'], items['Operation (in the field)']['event']),
                         (latest, latest))
        # Above the AHC and stood-down lines, which follow as before.
        ahc = self.make_event('operation', when(2024, 4, 10), attended=[self.other], ahc=[self.member])
        self.assertEqual([label for label in self.latest() if label.startswith('Operation')],
                         ['Operation (in the field)', 'Operation (as OL)', 'Operation (as AHC)'])
        self.assertEqual(self.latest()['Operation (as AHC)']['event'], ahc)

    def test_the_last_training_as_tl_or_ll_is_a_line_of_its_own(self):
        # Never led one: no line.
        self.make_event('training', when(2024, 2, 10), attended=[self.member])
        self.assertNotIn('Training (as TL or LL)', self.latest())
        # Named as TL in January, then at a training in February: the led line, under the training one, with its
        # own event and day. Flagged OL on a training counts as leading it too, as on the report.
        named = self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='Ann (TL)')
        items = self.latest()
        self.assertEqual(list(items), ['Operation (in the field)', 'Training (as participant)', 'Training (as TL or LL)', 'Meeting',
                                       'Community'])
        self.assertEqual((items['Training (as TL or LL)']['event'], items['Training (as TL or LL)']['day'],
                          items['Training (as participant)']['day']), (named, date(2024, 1, 10), date(2024, 2, 10)))
        flagged = self.make_event('training', when(2024, 3, 10), ol=[self.member])
        self.assertEqual(self.latest()['Training (as TL or LL)']['event'], flagged)

    def test_ol_is_counted_as_the_other_lines_are(self):
        # Flagged OL but as AHC: not in the field, so not as OL, as the report counts who led.
        operation = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=operation.period_set.first(), member=self.member, ahc=True, ol=True,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 10) + timedelta(hours=2))
        self.assertNotIn('Operation (as OL)', self.latest())
        self.assertEqual(activity_rows(self.member, NOW, member_entries(self.member), records_from(NOW))['total'].ol_days, 0)
        # As OL with times typed a year ahead: a day after today, so not yet.
        slip = self.make_event('operation', when(2024, 4, 10))
        Participant.objects.create(period=slip.period_set.first(), member=self.member, ol=True,
                                   en_route_at=when(2025, 4, 10), return_home_at=when(2025, 4, 10) + timedelta(hours=2))
        self.assertNotIn('Operation (as OL)', self.latest())
        # A test operation is left out, as on the report.
        test = self.make_event('operation', when(2024, 5, 10), ol=[self.member])
        Event.objects.filter(pk=test.pk).update(title='Test')
        self.assertNotIn('Operation (as OL)', self.latest())
        # As OL in the field: the day the report counts as an OL day.
        led = self.make_event('operation', when(2024, 5, 20), ol=[self.member], hours=30)
        rows = activity_rows(self.member, NOW, member_entries(self.member), records_from(NOW))
        self.assertEqual(rows['total'].ol_days, 2)
        self.assertEqual((self.latest()['Operation (as OL)']['event'], self.latest()['Operation (as OL)']['day']),
                         (led, date(2024, 5, 21)))

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
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
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

    def test_no_stood_down_line_for_an_operation_titled_as_a_heads_up_before_pages_told_one_apart(self):
        self.paging_began()
        self.make_event('meeting', when(2018, 6, 10), attended=[self.member])
        heads_up = super().make_event('operation', when(2018, 8, 10), no_time=[self.member])
        Event.objects.filter(pk=heads_up.pk).update(title='Heads up: search')
        self.assertNotIn('Operation (stood down)', self.latest())

    def test_before_pages_had_reply_templates_an_operation_not_run_was_called_off(self):
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
        # Pages from before 13 February 2019 had no reply template, so a heads-up cannot be told from a callout.
        self.make_event('meeting', when(2018, 6, 10), attended=[self.member])
        before = super().make_event('operation', when(2019, 2, 12), no_time=[self.member])
        self.assertEqual(self.latest()['Operation (stood down)']['event'], before)
        after = super().make_event('operation', when(2019, 2, 13), no_time=[self.member])
        # 8pm on the 12th, Pacific time, though the 13th in UTC.
        evening = super().make_event('operation', datetime(2019, 2, 13, 4, 0, tzinfo=dt_timezone.utc), no_time=[self.member])
        ids = [before.id, after.id, evening.id]
        not_run = operations_not_run(NOW, operations_that_ran(NOW, ids, records_from(NOW)), reply_templates_from(), ids)
        self.assertEqual(not_run, {before.id: NotRun('called_off', date(2019, 2, 12)),
                                   after.id: NotRun('heads_up', date(2019, 2, 13)),
                                   evening.id: NotRun('called_off', date(2019, 2, 12))})

    def test_no_stood_down_line_for_an_operation_begun_before_operation_times_were_logged(self):
        # Before OPERATION_TIMES_FROM most operations have nobody's times, so whether one ran is not known, as the
        # unit report shows it: nobody listed on one is said to have stood down from it.
        operation = self.make_event('operation', when(2011, 8, 12), no_time=[self.member, self.other])
        self.assertNotIn('Operation (stood down)', self.latest())
        with self.settings(ACTIVITY_REPORTS={'OPERATION_TIMES_FROM': 2011}):
            self.assertEqual(self.latest()['Operation (stood down)']['event'], operation)

    def test_stood_down_from_one_operation_though_another_listed_on_ran(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], no_time=[self.member])     # ran
        called_off = self.make_event('operation', when(2024, 3, 10), no_time=[self.member, self.other])
        self.assertEqual(self.latest().get('Operation (stood down)', {}).get('event'), called_off)

    def test_an_operation_saved_finishing_before_it_starts_has_not_finished_until_it_has_started(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        backwards = self.make_event('operation', NOW + timedelta(days=30), no_time=[self.member, self.other])
        Event.objects.filter(pk=backwards.pk).update(finish_at=when(2024, 2, 1))
        self.assertNotIn('Operation (stood down)', self.latest())
        self.assertEqual(self.not_run(), {})

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

    def test_whether_an_operation_ran_is_read_from_the_unit_s_first_year_on_as_the_unit_report_reads_it(self):
        # The records start in 2022. On each operation the member is listed without time, and the other signed
        # in and out (so no departure is logged), with no day counted from 2022 on: on 1 May 2024, by a sign-in
        # typed in 0024; and on the first, begun at 01:00 on 1 January 2022 local time, by an evening out that
        # began the day before and has most of its hours then. Neither ran, on either report: the member stood down.
        for year in (2023, 2024):
            self.make_event('training', when(year, 3, 10), attended=[self.member])
        first = self.make_event('operation', datetime(2022, 1, 1, 9, tzinfo=dt_timezone.utc), no_time=[self.member])
        Participant.objects.create(period=first.period_set.first(), member=self.other,
                                   signed_in_at=first.start_at - timedelta(hours=5),
                                   signed_out_at=first.start_at + timedelta(hours=1))
        self.assertEqual(records_from(NOW), date(2022, 1, 1))
        self.assertEqual(self.latest()['Operation (stood down)']['event'], first)
        mistyped = self.make_event('operation', when(2024, 5, 1), no_time=[self.member])
        Participant.objects.create(period=mistyped.period_set.first(), member=self.other,
                                   signed_in_at=datetime(24, 5, 1, 18, tzinfo=dt_timezone.utc),
                                   signed_out_at=when(2024, 5, 1) + timedelta(hours=2))
        self.assertEqual(self.latest()['Operation (stood down)']['event'], mistyped)
        years = unit_rows(NOW)['years']
        self.assertEqual((years[2022].operations['called_off'], years[2024].operations['called_off']), (1, 1))

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
        self.assertEqual(operations_that_ran(NOW, [called_off.id], records_from(NOW)), set())
        self.assertEqual(self.years()['2024'].unit_events['operation'], 0)

    def test_an_operation_ran_by_the_local_day_its_time_falls_on(self):
        # Attended only today, from 7am Pacific: it ran.
        today = self.make_event('operation', when(2024, 6, 15) - timedelta(hours=6), attended=[self.other])
        self.assertEqual(operations_that_ran(NOW, [today.id], records_from(NOW)), {today.id})
        # At 03:00 UTC on the 15th it is the evening of the 14th in Pacific time, so time logged
        # after midnight Pacific has not come yet, though its UTC date has.
        evening = datetime(2024, 6, 15, 3, 0, tzinfo=dt_timezone.utc)
        late = self.make_event('operation', when(2024, 6, 14))
        Participant.objects.create(period=late.period_set.first(), member=self.other,
                                   en_route_at=datetime(2024, 6, 15, 7, 30, tzinfo=dt_timezone.utc),
                                   return_home_at=datetime(2024, 6, 15, 9, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(operations_that_ran(evening, [late.id], records_from(evening)), set())

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

    def test_a_departure_logged_with_no_return_yet_means_the_operation_ran(self):
        # Yesterday's, saved as finished, with the other's Left logged and no return yet, as the reply to a
        # "Left?" page writes it: it ran, though no day of it counts yet, and the member did not stand down.
        self.make_event('training', when(2024, 1, 10), attended=[self.member, self.other])
        operation = self.make_event('operation', when(2024, 6, 14), no_time=[self.member])
        Participant.objects.create(period=operation.period_set.first(), member=self.other,
                                   en_route_at=when(2024, 6, 14) + timedelta(hours=1))
        since = records_from(NOW)

        def departed():
            return {(left.operation, left.member) for left in departure_entries(NOW, since, joined_on(NOW, since))}
        self.assertEqual(departed(), {(operation.id, self.other.id)})
        self.assertEqual(operations_that_ran(NOW, [operation.id], since), {operation.id})
        self.assertNotIn('Operation (stood down)', self.latest())
        self.assertNotIn('Operation (in the field)', {k for k, v in self.latest(self.other).items() if 'event' in v})
        # A guest's departure, the AHC's, one dated after today, and one for an operation not begun are not.
        Participant.objects.filter(member=self.other, period__event=operation).delete()
        guest, ahc = self.make_member('Gus', 'G'), self.make_member('Al', 'FM')
        period = operation.period_set.first()
        Participant.objects.create(period=period, member=guest, en_route_at=operation.start_at)
        Participant.objects.create(period=period, member=ahc, ahc=True, en_route_at=operation.start_at)
        Participant.objects.create(period=period, member=self.other, en_route_at=when(2024, 6, 16))
        ahead = self.make_event('operation', NOW + timedelta(days=1))
        Participant.objects.create(period=ahead.period_set.first(), member=self.other, en_route_at=NOW)
        self.assertEqual(departed(), set())
        self.assertEqual(self.latest()['Operation (stood down)']['event'], operation)

    def test_the_unit_is_asked_only_about_operations_that_may_have_been_called_off(self):
        # A meeting's leaders text alone asks for no usernames: the table names only trainings led.
        self.make_event('meeting', when(2024, 1, 3), attended=[self.member], leaders='Ann')
        with self.assertNumQueries(2):
            member_latest(self.member, NOW)
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='Ann (TL)')
        self.make_event('operation', when(2024, 2, 10), attended=[self.member, self.other])
        # The member's entries, the year the unit's records begin and the usernames, for the training they led:
        # no look at the unit.
        with self.assertNumQueries(3):
            member_latest(self.member, NOW)
        # Listed without time on an operation that has finished: that operation, and when those on it joined.
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], no_time=[self.member])
        with self.assertNumQueries(6):
            self.assertNotIn('Operation (stood down)', self.latest())
        # One still under way is not asked about.
        self.make_event('operation', NOW - timedelta(hours=2), no_time=[self.member], hours=24)
        with self.assertNumQueries(6):
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
        self.make_event('meeting', when(2024, 5, 31), attended=[self.member])
        latest = {i['label']: i for i in member_latest(self.member, evening)}
        self.assertEqual(latest['Training (as participant)']['day'], date(2024, 6, 14))
        # And how long ago is counted to the 14th: 14 days of the 30 to 30 June, under half a month, where the 15th
        # would be half and round up to a month.
        self.assertEqual(latest['Meeting']['ago'], 'Under a month')

    def test_how_long_ago_is_in_years_from_two(self):
        # From 23 and a half months, which rounds to 24: 30 June 2022 is 23 months and 16 of 31 days ago, and
        # 1 July 23 months and 14 of 30 days.
        two, under = self.make_member('Two', 'FM'), self.make_member('Under', 'FM')
        self.make_event('meeting', when(2022, 6, 30), attended=[two])
        self.make_event('meeting', when(2022, 7, 1), attended=[under])
        self.assertEqual((self.latest(two)['Meeting']['ago'], self.latest(under)['Meeting']['ago']),
                         ('2 years', '23 months'))

    def test_how_long_ago_reads_a_month_s_end_as_the_unit_report_does(self):
        # A calendar month after the 29th, 30th or 31st is the last day of a shorter month (months_after):
        # 29 February 2024 is a year before 28 February 2025, and 31 January a month before it.
        leap, january = self.make_member('Leap', 'FM'), self.make_member('January', 'FM')
        self.make_event('meeting', when(2024, 2, 29), attended=[leap])
        self.make_event('meeting', when(2025, 1, 31), attended=[january])
        now = when(2025, 2, 28)
        self.assertEqual([{i['label']: i for i in member_latest(m, now)}['Meeting']['ago'] for m in (leap, january)],
                         ['12 months', '1 month'])
        self.assertEqual(months_after(date(2024, 2, 29), 12), date(2025, 2, 28))

    def test_how_long_ago(self):
        # Each to the nearest: 31 months and 5 days is 3 years, 12 months and 26 days 13 months.
        self.make_event('operation', when(2021, 11, 10), attended=[self.member])
        self.make_event('training', when(2023, 5, 20), attended=[self.member])
        self.make_event('meeting', when(2024, 6, 10), attended=[self.member])
        self.make_event('community', when(2024, 5, 10), attended=[self.member])
        self.assertEqual([i['ago'] for i in member_latest(self.member, NOW)],
                         ['3 years', '13 months', 'Under a month', '1 month'])

    def test_matches_the_report(self):
        # The member page looks only at the member's own operations; the dates
        # must be the ones the report would count.
        self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member], hours=30)
        self.make_event('training', when(2024, 2, 10), attended=[self.member], hours=30)
        self.assertEqual(activity_rows(self.member, NOW, member_entries(self.member), records_from(NOW))['total'].ahc_days, 1)
        items = self.latest()
        self.assertEqual(items['Operation (as AHC)']['day'], date(2024, 1, 10))
        self.assertEqual(items['Training (as participant)']['day'], date(2024, 2, 11))


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
        self.assertContains(response, '<tr><td>Training (as participant)</td><td>None</td><td></td><td></td></tr>', html=True)
        self.assertNotContains(response, 'Operation (as OL)')
        # As OL: its line, under the one in the field.
        self.make_event('operation', when(2024, 2, 10), ol=[self.member])
        response = client.get(self.member.get_absolute_url())
        page = response.content.decode()
        self.assertContains(response, '<tr><td>Operation (as OL)</td><td><a href="{}">Event</a></td><td>10 Feb 2024</td>'
                            '<td>4 months</td></tr>'.format(reverse('event_detail', args=[Event.objects.latest('id').id])),
                            html=True)
        self.assertLess(page.index('<td>Operation (in the field)</td>'), page.index('<td>Operation (as OL)</td>'))



LOGGER = 'main.views.member_views'
POSTGRES = connection.vendor == 'postgresql'


def database_error(*args):
    """A real error from the database, which on Postgres also aborts the transaction it is in."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM no_such_table')


class LastTableGuard:
    """The member page holds a member's addresses, phones and emergency contacts, so its Activity section, the Last
    table, never breaks or stalls it: if building the table fails, or on Postgres its queries run, between them,
    past the team's limit (LAST_TABLE_SECONDS), the page shows without the section, as before the reports, and the
    error is logged. Run inside a test's transaction, where the section's own is a savepoint
    (MemberPageGuardTestCase), and outside one, as the site serves the page, its views not atomic
    (MemberPageGuardOwnTransactionTestCase)."""
    make_member, make_event = ActivityTestCase.make_member, ActivityTestCase.make_event

    def setUp(self):
        super().setUp()
        cache.clear()
        self.enterContext(mock.patch('django.utils.timezone.now', return_value=NOW))
        self.member, self.other = self.make_member('Ann', 'FM'), self.make_member('Bob', 'FM')
        self.make_event('operation', when(2024, 1, 10), attended=[self.member])
        Phone.objects.create(member=self.member, number='4155550100')
        Address.objects.create(member=self.member, type='Home', address1='1 Main Street', city='Town', state='CA',
                               zip='94000')
        EmergencyContact.objects.create(member=self.member, name='Kin Test', number='4155550199', type='Mobile')
        self.client.force_login(self.other)
        self.limits = []

    def page(self):
        """The member page, which shows, whatever the section does, with the member's contact details."""
        response = self.client.get(self.member.get_absolute_url())
        for detail in ('415-555-0100', '1 Main Street', 'Kin Test: 415-555-0199'):
            self.assertContains(response, detail)
        return response

    def assertShown(self, response):
        self.assertContains(response, '<strong>Activity</strong>')
        self.assertContains(response, '<td>Operation (in the field)</td>', html=True)

    def assertLeftOut(self, response, logs, cause):
        """The page as before the reports, no Activity section, and the error logged with the member's id and its
        traceback, which names `cause`."""
        self.assertNotContains(response, '<strong>Activity</strong>')
        self.assertNotContains(response, 'id="activityTbl"')
        [record] = logs.records
        self.assertIn('member {}'.format(self.member.id), record.getMessage())
        self.assertIsNotNone(record.exc_info)
        self.assertIn('Traceback', logs.output[0])
        self.assertIn(cause, logs.output[0])

    def slowed(self, *waits):
        """member_latest, after each of `waits`, seconds waited in the database, as the test's data is too small
        for any of the table's queries to take long; the limit in force is read before each."""
        def slowed(*args):
            for wait in waits:
                self.limits.append(self.limit())
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_sleep(%s)', [wait])
            return member_latest(*args)
        return mock.patch('main.views.member_views.member_latest', slowed)

    def limit(self):
        """The time limit of the next statement, in seconds; 0 for none."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXTRACT(EPOCH FROM current_setting('statement_timeout')::interval)")
            return float(cursor.fetchone()[0])

    def test_a_failure_in_building_the_last_table_leaves_the_section_out(self):
        # A database error in each place: the cache's read of its tables, records_from, member_latest, and the
        # template, which meets a query left lazy in the table's data.
        lazy = Event.objects.filter(id__in=RawSQL('SELECT id FROM no_such_table', []))
        for place, failure in (('main.lib.report_cache._read', database_error),
                               ('main.lib.counting.records_from', database_error),
                               ('main.views.member_views.member_latest', database_error),
                               ('main.views.member_views.member_latest', lambda *args: [{'label': 'Meeting',
                                                                                         'event': lazy}])):
            with self.subTest(place):
                cache.clear()       # so that records_from is built, not read from the cache
                with mock.patch(place, failure), self.assertLogs(LOGGER, 'ERROR') as logs:
                    self.assertLeftOut(self.page(), logs, 'no_such_table')
                # The next load, on the same connection, works, section and all.
                self.assertShown(self.page())

    @skipUnless(POSTGRES, "statement_timeout is Postgres's")
    def test_a_query_past_the_time_limit_leaves_the_section_out(self):
        # The maintainer's test: a limit too short for the table's queries.
        with self.slowed(0.2):
            with override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0.05}), \
                    self.assertLogs(LOGGER, 'ERROR') as logs:
                self.assertLeftOut(self.page(), logs, 'canceling statement due to statement timeout')
            # With the default, 5 seconds, the same wait shows the section.
            self.assertShown(self.page())
        short, default = self.limits
        self.assertTrue(0 < short <= 0.05 and 4 < default <= 5, self.limits)

    @skipUnless(POSTGRES, "statement_timeout is Postgres's")
    def test_the_time_limit_is_for_the_table_s_queries_together(self):
        # Two queries, each within the limit, are past it together: the second has only what the first left.
        with self.slowed(0.2, 0.2), override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0.3}), \
                self.assertLogs(LOGGER, 'ERROR') as logs:
            self.assertLeftOut(self.page(), logs, 'canceling statement due to statement timeout')
        first, second = self.limits
        self.assertTrue(0 < second <= 0.1 < first <= 0.3, self.limits)
        # Time between the queries counts: with none left, the next is not run.
        with mock.patch('main.views.member_views.member_latest', lambda *args: time.sleep(0.1) or member_latest(*args)), \
                override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0.05}), \
                self.assertLogs(LOGGER, 'ERROR') as logs:
            self.assertLeftOut(self.page(), logs, 'No time left of 0.05 seconds')

    @skipUnless(POSTGRES, "statement_timeout is Postgres's")
    def test_a_team_may_set_no_time_limit(self):
        own = self.limit()
        with self.slowed(0.2), override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0}):
            self.assertShown(self.page())
        self.assertEqual(self.limits, [own])

    @skipUnless(POSTGRES, "statement_timeout is Postgres's")
    def test_the_time_limit_ends_with_the_section(self):
        # Whether the table's queries ran within the limit or one was cut off, the connection's own limit is back
        # after it, so that a slow statement after it runs to its end.
        own = self.limit()
        with override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0.1}):
            for slowed in (False, True):
                with self.slowed(0.2) if slowed else nullcontext(), \
                        self.assertLogs(LOGGER, 'ERROR') if slowed else self.assertNoLogs(LOGGER, 'ERROR'):
                    response = self.page()
                self.assertEqual('<strong>Activity</strong>' in response.content.decode(), not slowed)
                self.assertEqual(self.limit(), own)
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_sleep(0.2)')

    @skipIf(POSTGRES, "statement_timeout is Postgres's")
    def test_the_time_limit_is_nothing_on_other_databases(self):
        with override_settings(ACTIVITY_REPORTS={'LAST_TABLE_SECONDS': 0.001}), \
                CaptureQueriesContext(connection) as queries:
            self.assertShown(self.page())
        self.assertFalse([query for query in queries if 'statement_timeout' in query['sql']])

    def test_the_reports_cache_is_not_in_the_database(self):
        # The section is rolled back, which would undo what a cache kept in the database was given in it.
        self.assertNotIsInstance(caches['default'], BaseDatabaseCache)


class MemberPageGuardTestCase(LastTableGuard, TestCase):
    pass


class MemberPageGuardOwnTransactionTestCase(LastTableGuard, TransactionTestCase):
    pass
