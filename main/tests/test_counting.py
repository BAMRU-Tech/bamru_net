"""The counting rules (main.lib.counting): days, hours, events, who led, what ran, and what is left out."""
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from main.lib.activity import glossary, member_activity
from main.lib.counting import (TYPES, activity_rows, count_entry_days, day_hours, entry_hours, entry_led, first_claims,
                               hours_by_local_day, member_entries, member_latest, reported_events, unit_since)
from main.models import DoAvailable, Event, Member, Participant, Period
from main.tests.helpers import NOW, ActivityTestCase, when


class DaysTestCase(TestCase):
    def days(self, start, end):
        """Days counted for time logged between two local (Pacific) times in March 2024,
        each given as (day of the month, hour, minute)."""
        def utc(day, hour, minute):   # PST is UTC-8 until 10 March
            return datetime(2024, 3, day, hour, minute, tzinfo=dt_timezone.utc) + timedelta(hours=8)
        return [d.day for d in list(day_hours(utc(*start), utc(*end), None, None))]

    def test_days(self):
        cases = [
            ('a long single day',                 (5, 5, 0), (5, 20, 0), [5]),
            ('home just after midnight',          (5, 8, 0), (6, 0, 40), [5]),
            ('a short night search',              (5, 20, 0), (6, 4, 0), [5]),
            ('a night search, mostly after midnight', (5, 23, 0), (6, 9, 0), [6]),
            ('up the evening before',             (5, 17, 0), (6, 20, 0), [5, 6]),
            ('up the evening before, a day later', (5, 20, 0), (6, 20, 0), [5, 6]),
            ('up late the night before',          (5, 22, 30), (6, 20, 0), [6]),
            ('four days in one entry',            (4, 18, 0), (7, 15, 0), [4, 5, 6, 7]),
            ('four days, home after midnight',    (4, 18, 0), (8, 1, 0), [4, 5, 6, 7]),
            ('half an hour',                      (5, 19, 0), (5, 19, 30), [5]),
            # The edges of the rules: 2 hours on a day counts it, 12 hours in all is still one day.
            ('exactly two hours on the second day',       (5, 10, 0), (6, 2, 0), [5, 6]),
            ('a minute under two hours on the second day', (5, 10, 0), (6, 1, 59), [5]),
            ('exactly twelve hours across midnight',      (5, 20, 0), (6, 8, 0), [6]),
            ('twelve hours and a minute across midnight', (5, 20, 0), (6, 8, 1), [5, 6]),
            # Before the clocks went forward on 10 March, which the helper does not follow.
            ('exactly seven days',                        (1, 12, 0), (8, 12, 0), [1, 2, 3, 4, 5, 6, 7, 8]),
            ('seven days and a minute: a slip, one day',  (1, 12, 0), (8, 12, 1), [1]),
        ]
        for name, start, end, expected in cases:
            self.assertEqual(self.days(start, end), expected, name)

    def test_daylight_saving(self):
        # Clocks went forward on 10 March 2024 and back on 3 November. An entry
        # is measured by the time that passed, not by the clock.
        def utc(month, day, hour, minute):
            return datetime(2024, month, day, hour, minute, tzinfo=dt_timezone.utc)
        # 9 March 20:00 PST to 10 March 08:30 PDT is 11.5 hours: one day.
        self.assertEqual(len(list(day_hours(utc(3, 10, 4, 0), utc(3, 10, 15, 30), None, None))), 1)
        # 2 November 20:00 PDT to 3 November 07:30 PST is 12.5 hours: two days.
        self.assertEqual(len(list(day_hours(utc(11, 3, 3, 0), utc(11, 3, 15, 30), None, None))), 2)

    def test_entry_hours_are_those_up_to_today_of_an_event_started(self):
        def utc(month, day, hour):
            return datetime(2024, month, day, hour, 0, tzinfo=dt_timezone.utc)
        # From 1pm on the 14th to 1pm on the 16th, read on the evening of the 15th, Pacific time.
        times = (utc(6, 14, 20), utc(6, 16, 20), None, None)
        self.assertEqual(entry_hours(*times, utc(6, 14, 20), utc(6, 16, 3)),
                         {date(2024, 6, 14): 11, date(2024, 6, 15): 24})
        # Nothing for an event that has not started, whatever its times.
        self.assertEqual(entry_hours(*times, utc(6, 16, 4), utc(6, 16, 3)), {})

    def test_hours_by_local_day(self):
        def utc(month, day, hour, minute=0):
            return datetime(2024, month, day, hour, minute, tzinfo=dt_timezone.utc)
        # The days the clocks change have 23 and 25 hours; a day the time ends at midnight on gets none.
        self.assertEqual(hours_by_local_day(utc(3, 10, 8), utc(3, 11, 7)), {date(2024, 3, 10): 23})
        self.assertEqual(hours_by_local_day(utc(11, 3, 7), utc(11, 4, 8)), {date(2024, 11, 3): 25})
        # 22:00 to 01:30 Pacific in winter: two hours on one day, an hour and a half on the next.
        self.assertEqual(hours_by_local_day(utc(1, 11, 6), utc(1, 11, 9, 30)),
                         {date(2024, 1, 10): 2, date(2024, 1, 11): 1.5})

    def test_seven_days_by_the_clock_in_the_weeks_the_clocks_change(self):
        # The 7-day limit reads the local clock; the hours counted are the time that passed.
        def utc(month, day, hour, minute):
            return datetime(2024, month, day, hour, minute, tzinfo=dt_timezone.utc)
        def counted(start, end):
            hours = day_hours(start, end, None, None)
            return len(hours), round(sum(hours.values()), 2)
        # Spring: 7 March noon PST to 14 March noon PDT is 7 days by the clock, 167 hours.
        self.assertEqual(counted(utc(3, 7, 20, 0), utc(3, 14, 19, 0)), (8, 167))
        # Half an hour more is past the limit by the clock, though under 168 hours.
        self.assertEqual(counted(utc(3, 7, 20, 0), utc(3, 14, 19, 30)), (1, 0))
        # Autumn: 31 October noon PDT to 7 November noon PST is 7 days by the clock, 169 hours.
        self.assertEqual(counted(utc(10, 31, 19, 0), utc(11, 7, 20, 0)), (8, 169))
        self.assertEqual(counted(utc(10, 31, 19, 0), utc(11, 7, 20, 1)), (1, 0))

    def test_new_year(self):
        days = list(day_hours(datetime(2024, 1, 1, 1, 0, tzinfo=dt_timezone.utc),      # 31 Dec 17:00 PST
                              datetime(2024, 1, 2, 2, 0, tzinfo=dt_timezone.utc), None, None))
        self.assertEqual(days, [date(2023, 12, 31), date(2024, 1, 1)])

    def test_no_time_logged(self):
        start = datetime(2024, 3, 5, 20, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(list(day_hours(None, None, None, None)), [])
        self.assertEqual(list(day_hours(start, None, None, None)), [])
        self.assertEqual(list(day_hours(start, start, None, None)), [])
        self.assertEqual(list(day_hours(start, start - timedelta(days=2), None, None)), [])

    def test_sign_in_times_are_used_without_travel_times(self):
        start = datetime(2024, 3, 5, 20, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(list(day_hours(None, None, start, start + timedelta(hours=3))), [date(2024, 3, 5)])
        # With one travel time only, the pair is not whole: the sign-in times are used.
        self.assertEqual(day_hours(start - timedelta(days=3), None, start, start + timedelta(hours=3)),
                         {date(2024, 3, 5): 3})


class ActivityRowsTestCase(ActivityTestCase):
    def test_no_activity(self):
        self.make_event('training', when(2024, 3, 1), no_time=[self.member])
        self.assertIsNone(activity_rows(self.member, NOW))
        self.assertIsNone(member_activity(self.member, NOW))

    def test_days_attended_out_of_days_active(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member, self.other])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], no_time=[self.member])
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (1, 2))
        self.assertEqual(self.days(year, 'training'), (1, 1))
        self.assertEqual(year.all_hours, 8)

    def test_each_calendar_day_counts(self):
        # Noon on the 10th to noon on the 12th touches three days.
        self.make_event('training', when(2024, 1, 10), attended=[self.other], hours=48)
        self.make_event('training', when(2024, 1, 10), attended=[self.member], hours=4)
        self.assertEqual(self.days(self.years()['2024'], 'training'), (1, 3))
        self.assertEqual(self.days(self.years(self.other)['2024'], 'training'), (3, 3))

    def test_two_events_on_one_day_count_once(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'meeting'), (1, 1))

    def test_days_across_types_count_once(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        self.make_event('training', when(2024, 1, 11), attended=[self.member])
        self.make_event('operation', when(2024, 1, 12), attended=[self.other])
        year = self.years()['2024']
        # The meeting and the training of the 10th were at the same hours, which count once.
        self.assertEqual((year.all_days, year.all_active_days, year.all_hours), (2, 3, 8))
        # Each day is counted under the first type attended on it.
        self.assertEqual(year.first_days, {'operation': 0, 'training': 2, 'meeting': 0, 'community': 0})

    def test_called_off_operations(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member])
        # Members listed, and none logged time.
        self.make_event('operation', when(2024, 2, 10), no_time=[self.member, self.other])
        # Only the AHC logged time: called off, but the AHC did the work.
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member], no_time=[self.other])
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (2, 2))
        self.assertEqual((year.ol_days, year.ahc_days, year.do_days), (0, 1, 0))
        self.assertEqual(year.all_hours, 6)
        # For the member who was only listed, it is not a unit active day.
        self.make_event('meeting', when(2024, 1, 5), attended=[self.other])
        self.assertEqual(self.days(self.years(self.other)['2024'], 'operation'), (0, 1))
        # Someone with only AHC time on a called-off operation has a report.
        solo = self.make_member('Sol', 'FM')
        self.make_event('operation', when(2024, 5, 10), ahc=[solo])
        self.assertEqual(self.days(self.years(solo)['2024'], 'operation'), (1, 1))

    def test_ol_counts_like_other_responders(self):
        # An OL with times attended, and the operation ran even with nobody else.
        self.make_event('operation', when(2024, 1, 10), ol=[self.member])
        # An OL without times did not attend.
        event = self.make_event('operation', when(2024, 2, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ol=True)
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (1, 2))
        self.assertEqual((year.ol_days, year.ol_hours), (1, 4))

    def test_days_as_ahc_are_days_attended(self):
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        # Listed as AHC without times: no duty.
        event = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True)
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (1, 2))
        self.assertEqual((year.ahc_days, year.ahc_hours, year.all_days), (1, 2, 1))

    def test_ahc_for_one_period_and_in_the_field_for_another(self):
        event = self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member])
        second = Period.objects.create(event=event, position=2)
        for member in (self.member, self.other):
            Participant.objects.create(period=second, member=member, en_route_at=when(2024, 1, 11),
                                       return_home_at=when(2024, 1, 11) + timedelta(hours=4))
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (2, 2))
        self.assertEqual(year.ahc_days, 1)
        # AHC and in the field on the same day is one day, in the field.
        third = Period.objects.create(event=event, position=3)
        Participant.objects.create(period=third, member=self.member, ahc=True, en_route_at=when(2024, 1, 11),
                                   return_home_at=when(2024, 1, 11) + timedelta(hours=2))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year.ahc_days), ((2, 2), 1))

    def test_ahc_flag_means_nothing_off_operations(self):
        event = self.make_event('training', when(2024, 1, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 1, 10),
                                   return_home_at=when(2024, 1, 10) + timedelta(hours=5))
        self.make_event('operation', when(2024, 2, 10), attended=[self.member], hours=3)
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'training'), (1, 1))
        self.assertEqual((year.hours['training'], year.hours['operation'], year.ahc_hours), (5, 3, 0))
        # A training only someone flagged AHC logged time on still ran.
        self.make_event('training', when(2024, 3, 10), ahc=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'training'), (2, 2))

    def test_ahc_time_before_and_after_everything_else_is_kept(self):
        # AHC time on called-off operations, before the first and after the last other event.
        self.make_event('operation', when(2023, 1, 10), ahc=[self.member])
        self.make_event('meeting', when(2023, 6, 10), attended=[self.member])
        self.make_event('operation', when(2024, 1, 10), ahc=[self.member])
        rows = activity_rows(self.member, NOW)
        self.assertEqual((rows['total'].all_days, rows['total'].all_hours), (3, 8))
        alum = self.make_member('Cat', 'MA')
        self.make_event('meeting', when(2023, 6, 10), attended=[alum])
        self.make_event('operation', when(2024, 1, 10), ahc=[alum])
        self.assertEqual(activity_rows(alum, NOW)['total'].all_hours, 6)

    def test_the_unit_is_read_from_the_members_first_day(self):
        self.make_event('training', when(2020, 1, 10), attended=[self.other])
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        days, events = unit_since(date(2024, 1, 10), NOW)
        self.assertEqual((days['training'], list(events['training'].values())), ({date(2024, 1, 10)}, [date(2024, 1, 10)]))
        self.assertEqual(self.days(activity_rows(self.member, NOW)['total'], 'training'), (1, 1))

    def test_a_unit_entry_begun_seven_days_before_the_first_day_reaches_it(self):
        def local(*when):
            return timezone.make_aware(datetime(*when))
        # The member's first day is the day an evening training started, 10 February; her time is the next morning.
        mine = Event.objects.create(type='training', title='Mine', location='Here', leaders='',
                                    start_at=local(2024, 2, 10, 23), finish_at=local(2024, 2, 11, 16))
        Participant.objects.create(period=mine.period_set.first(), member=self.member,
                                   en_route_at=local(2024, 2, 11, 8), return_home_at=local(2024, 2, 11, 12))
        # Someone else's seven days end at 2am on the 10th, two hours in the member's time: begun 6 days 22 hours
        # before her first day, as long before it as an entry that still counts can begin, it reaches it.
        for kind, times in (('training', ('en_route_at', 'return_home_at')), ('meeting', ('signed_in_at', 'signed_out_at'))):
            week = Event.objects.create(type=kind, title='Week', location='Here', leaders='',
                                        start_at=local(2024, 2, 3, 2), finish_at=local(2024, 2, 10, 2))
            Participant.objects.create(period=week.period_set.first(), member=self.other,
                                       **dict(zip(times, (local(2024, 2, 3, 2), local(2024, 2, 10, 2)))))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'training'), self.days(year, 'meeting')), ((1, 2), (0, 1)))
        # In the week the clocks go back, seven local days are 169 hours: an entry from 2am on 28 October to
        # 2am on 4 November began 167 hours before the 4th, and reaches it.
        autumn = Event.objects.create(type='community', title='Week', location='Here', leaders='',
                                      start_at=local(2024, 10, 28, 2), finish_at=local(2024, 11, 4, 2))
        Participant.objects.create(period=autumn.period_set.first(), member=self.other,
                                   en_route_at=local(2024, 10, 28, 2), return_home_at=local(2024, 11, 4, 2))
        self.assertEqual(unit_since(date(2024, 11, 4), NOW + timedelta(days=200))[0]['community'] & {date(2024, 11, 4)},
                         {date(2024, 11, 4)})
        # The week began before the member's first day, so it is not one of the unit's events for her.
        self.assertEqual((year.events['training'], year.unit_events['training']), (1, 1))

    def test_today_is_the_local_day(self):
        # 8pm Pacific on 15 June, already the 16th in UTC.
        evening = datetime(2024, 6, 16, 3, 0, tzinfo=dt_timezone.utc)
        training = self.make_event('training', when(2024, 6, 15))
        tomorrow = datetime(2024, 6, 16, 15, 0, tzinfo=dt_timezone.utc)     # 8am Pacific on the 16th
        for member in (self.member, self.other):
            Participant.objects.create(period=training.period_set.first(), member=member,
                                       en_route_at=tomorrow, return_home_at=tomorrow + timedelta(hours=4))
        # Time typed for tomorrow counts nothing yet, for the member or for the unit.
        self.assertIsNone(activity_rows(self.member, evening))
        self.assertEqual(unit_since(date(2024, 6, 1), evening)[1]['training'], {})
        entries = member_entries(self.member)
        count_entry_days(entries, evening)
        self.assertEqual([(p.days, p.left_out_hours) for p in entries], [(0, 4)])
        # The next morning it does.
        morning = tomorrow + timedelta(hours=5)
        self.assertEqual(self.days(activity_rows(self.member, morning)['total'], 'training'), (1, 1))

    def test_an_event_is_placed_by_the_local_day_it_started(self):
        self.make_event('training', when(2023, 12, 1), attended=[self.member])
        # Started at 8pm Pacific on 31 December, which is 1 January in UTC; the other member was there.
        late = Event.objects.create(type='training', title='Late', location='Here', leaders='',
                                    start_at=datetime(2024, 1, 1, 4, 0, tzinfo=dt_timezone.utc),
                                    finish_at=datetime(2024, 1, 1, 6, 0, tzinfo=dt_timezone.utc))
        Participant.objects.create(period=late.period_set.first(), member=self.other,
                                   en_route_at=late.start_at, return_home_at=late.finish_at)
        # One that started on 31 December, which the member joined only on 1 January.
        two_days = self.make_event('training', when(2023, 12, 31))
        Participant.objects.create(period=two_days.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 1, 1), return_home_at=when(2024, 1, 1) + timedelta(hours=4))
        years = self.years()
        self.assertEqual([(y, years[y].events['training'], years[y].unit_events['training'], years[y].days['training'])
                          for y in ('2023', '2024')], [('2023', 2, 3, 1), ('2024', 0, 0, 1)])

    def test_the_unit_counts_from_sign_in_times_alone(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        signed = self.make_event('training', when(2024, 2, 10))
        Participant.objects.create(period=signed.period_set.first(), member=self.other,
                                   signed_in_at=when(2024, 2, 10), signed_out_at=when(2024, 2, 10) + timedelta(hours=3))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'training'), year.unit_events['training']), ((1, 2), 2))

    def test_another_event_on_the_members_first_day_is_a_unit_event(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        self.make_event('training', when(2024, 1, 10) - timedelta(hours=3), attended=[self.other])
        # An all-day event starts at local midnight, the very start of the member's first day.
        self.make_event('meeting', timezone.make_aware(datetime(2024, 1, 10)), attended=[self.other])
        year = self.years()['2024']
        self.assertEqual((year.events['training'], year.unit_events['training']), (1, 2))
        self.assertEqual(year.unit_events['meeting'], 1)

    def test_a_unit_event_after_the_first_day_counts_whenever_its_times_were_typed(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        # An event of March whose only times are typed for January: a slip, but the event ran, in March.
        march = self.make_event('training', when(2024, 3, 10))
        Participant.objects.create(period=march.period_set.first(), member=self.other,
                                   en_route_at=when(2023, 12, 1), return_home_at=when(2023, 12, 1) + timedelta(hours=4))
        self.assertEqual(self.years()['2024'].unit_events['training'], 2)

    def test_someone_no_longer_a_member_is_counted_to_their_last_day(self):
        # A former member, and a guest: the unit's later days are not theirs to have attended.
        for status in ('MN', 'G'):
            gone = self.make_member('Dan' + status, status)
            self.make_event('training', when(2024, 1, 10), attended=[gone])
            self.make_event('training', when(2024, 3, 10), attended=[self.other])
            rows = activity_rows(gone, NOW)
            self.assertEqual(self.days(rows['total'], 'training'), (1, 1), status)
            self.assertEqual([m.period for m in rows['months']], [(2024, 1)], status)
            Event.objects.all().delete()

    def test_an_operation_flagged_ahc_and_ol_is_attended_as_ahc(self):
        operation = self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member])
        Participant.objects.filter(period__event=operation, member=self.member).update(ol=True)
        year = self.years()['2024']
        self.assertEqual((year.ol_events, year.ahc_events, year.ol_days, year.ahc_days, year.ol_hours),
                         (0, 1, 0, 1, 0))

    def test_ol_flag_off_operations_is_leading(self):
        self.make_event('training', when(2024, 1, 10), ol=[self.member])
        year = self.years()['2024']
        self.assertEqual((year.led_days['training'], year.ol_days), (1, 0))

    def test_do_weeks(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        for quarter, week in ((1, 3), (2, 1), (4, 1)):   # the last has not started
            DoAvailable.objects.create(member=self.member, year=2024, quarter=quarter, week=week,
                                       assigned=True)
        DoAvailable.objects.create(member=self.member, year=2024, quarter=1, week=5, available=True)
        self.assertEqual(self.years()['2024'].do_days, 2)

    def test_hours_go_to_the_days_they_fell_on(self):
        # 8pm on 31 December to 4pm on 1 January, Pacific time: a day in each year.
        start = datetime(2024, 1, 1, 4, 0, tzinfo=dt_timezone.utc)
        self.make_event('operation', start, ol=[self.member], hours=20)
        years = self.years()
        self.assertEqual([(years[y].days['operation'], years[y].hours['operation'], years[y].ol_hours)
                          for y in ('2023', '2024')], [(1, 4, 4), (1, 16, 16)])
        # An hour before midnight is too short to count as a day: it goes with the day after.
        late = datetime(2024, 3, 10, 7, 0, tzinfo=dt_timezone.utc)      # 11pm on 9 March
        self.assertEqual(day_hours(late, late + timedelta(hours=16), None, None), {date(2024, 3, 10): 16})
        # A short entry across midnight is one day, with all its hours.
        self.assertEqual(day_hours(late, late + timedelta(hours=4), None, None), {date(2024, 3, 10): 4})
        # An entry too long to be right counts its first day and no hours.
        self.assertEqual(day_hours(late, late + timedelta(days=8), None, None), {date(2024, 3, 9): 0})

    def test_a_do_week_counts_from_the_hour_its_shift_starts(self):
        DoAvailable.objects.create(member=self.member, year=2024, quarter=2, week=1, assigned=True)
        start = timezone.make_aware(DoAvailable.shift_start(2024, 2, 1))
        self.assertIsNone(activity_rows(self.member, start - timedelta(hours=2)))
        self.assertEqual(activity_rows(self.member, start)['total'].do_days, 1)
        # The same whatever timezone the time now is given in: 8am Pacific is 3pm UTC.
        half_past_seven = (start - timedelta(minutes=30)).astimezone(dt_timezone.utc)
        self.assertIsNone(activity_rows(self.member, half_past_seven))
        self.assertEqual(activity_rows(self.member, half_past_seven + timedelta(hours=1))['total'].do_days, 1)

    def test_time_entered_for_a_day_after_today_is_not_counted_yet(self):
        event = self.make_event('training', when(2024, 6, 1), attended=[self.member])
        Participant.objects.filter(period__event=event).update(
            en_route_at=when(2025, 6, 1), return_home_at=when(2025, 6, 1) + timedelta(hours=4))
        self.assertIsNone(activity_rows(self.member, NOW))
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        rows = activity_rows(self.member, NOW)
        self.assertEqual(([r.period for r in rows['years']], rows['total'].all_days), ([2024], 1))

    def test_events_led(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member, self.other],
                        leaders='Ann, Bob')
        self.make_event('training', when(2024, 2, 10), attended=[self.member], leaders='Bob')
        # Named as a leader, but not there.
        self.make_event('training', when(2024, 3, 10), attended=[self.other], leaders='Ann')
        self.make_event('meeting', when(2024, 4, 10), attended=[self.member], leaders='Ann')
        self.make_event('community', when(2024, 5, 10), attended=[self.member], leaders='ANN')
        # An operation's leaders text is not used; OLs are flagged.
        self.make_event('operation', when(2024, 6, 10), attended=[self.member], leaders='Ann')
        year = self.years()['2024']
        self.assertEqual(year.led_days, {'operation': 0, 'training': 1, 'meeting': 1, 'community': 1})
        self.assertEqual(year.led_hours['training'], 4)

    def test_leaders_are_members_whose_username_is_in_the_text(self):
        for leaders, led in (('Ann', 1), ('Bob, ANN', 1), ('Ann (TL), Bob (LL)', 1), ('Bob and Ann', 1),
                             ('Bob & Ann(TL, LL)', 1), ('Bob/Ann; Cy', 1), ('TL: ann', 1),
                             ('Annabel', 0), ('Joann', 0), ('Ann2', 0), ('Bob', 0), ('', 0)):
            Event.objects.all().delete()
            self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders=leaders)
            self.assertEqual(self.years()['2024'].led_days['training'], led, leaders)

    def test_an_entry_too_long_to_be_right(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        # Someone else's slip adds one unit active day, not nineteen...
        self.make_event('training', when(2024, 2, 1), attended=[self.other], hours=24 * 19)
        self.make_event('operation', when(2024, 3, 1), attended=[self.other], no_time=[self.member], hours=24 * 8)
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'training'), self.days(year, 'operation')), ((1, 2), (0, 1)))
        # The member's own slip is one day and no hours. Seven days is still fine.
        self.make_event('meeting', when(2024, 4, 1), attended=[self.member], hours=24 * 7 + 1)
        self.make_event('community', when(2024, 5, 1), attended=[self.member], hours=24 * 7)
        year = self.years()['2024']
        self.assertEqual((year.days['meeting'], year.days['community'], year.all_hours), (1, 8, 4 + 168))
        # Someone whose only entry is a slip still has a report.
        self.assertEqual(activity_rows(self.other, NOW)['total'].all_days, 2)

    def test_ahc_on_a_called_off_operation(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member], no_time=[self.other])
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year.ahc_days), ((1, 1), 1))

    def test_ahc_days_count_for_the_member_everywhere(self):
        # AHC on a called-off operation, and on a day of an operation when nobody was in the field.
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member])
        event = self.make_event('operation', when(2024, 4, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 4, 12), return_home_at=when(2024, 4, 12) + timedelta(hours=3))
        rows = activity_rows(self.member, NOW)
        year = rows['years'][0]
        self.assertEqual((self.days(year, 'operation'), year.ahc_days), ((2, 3), 2))
        self.assertEqual((year.all_days, year.all_active_days), (2, 3))
        months = {r.period: r for r in rows['months']}
        self.assertEqual(self.days(months[(2024, 3)], 'operation'), (1, 1))
        self.assertEqual((months[(2024, 3)].all_days, months[(2024, 3)].all_active_days), (1, 1))
        self.assertEqual(self.days(months[(2024, 4)], 'operation'), (1, 2))

    def test_ahc_entry_too_long_to_be_right(self):
        event = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 30))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year.ahc_days, year.ahc_hours), ((1, 1), 1, 0))

    def test_time_logged_before_the_event(self):
        # Times typed a month before the event's date: the window starts at the time
        # logged, and the unit's days are fetched from there.
        event = self.make_event('training', when(2024, 1, 20))
        for member in (self.member, self.other):
            Participant.objects.create(period=event.period_set.first(), member=member,
                                       en_route_at=when(2023, 12, 20), return_home_at=when(2023, 12, 20) + timedelta(hours=4))
        self.make_event('training', when(2023, 12, 28), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual([(r.period, self.days(r, 'training')) for r in rows['years']],
                         [(2023, (1, 2)), (2024, (0, 0))])

    def test_alumni_count_towards_the_units_days_and_guests_do_not(self):
        alum, gone, guest = (self.make_member(name, status)
                             for name, status in (('Cat', 'MA'), ('Dan', 'MN'), ('Gus', 'G')))
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        self.make_event('training', when(2024, 2, 10), attended=[alum])
        self.make_event('training', when(2024, 3, 10), attended=[gone])
        self.make_event('training', when(2024, 4, 10), attended=[guest])
        self.make_event('operation', when(2024, 4, 20), attended=[guest], no_time=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'training'), (1, 3))
        # The guest's own days still count as unit active days for them.
        year = self.years(guest)['2024']
        self.assertEqual((self.days(year, 'training'), self.days(year, 'operation')), ((1, 1), (1, 1)))

    def test_a_slip_affects_only_the_member_who_made_it(self):
        event = self.make_event('operation', when(2024, 3, 1), attended=[self.member], hours=30)
        Participant.objects.create(period=event.period_set.first(), member=self.other,
                                   en_route_at=when(2024, 3, 1), return_home_at=when(2024, 3, 20))
        # The member with good times: two days of two unit active days, and their hours.
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year.hours['operation']), ((2, 2), 30))
        # The member who made the slip: one day, no hours.
        year = self.years(self.other)['2024']
        self.assertEqual((self.days(year, 'operation'), year.hours['operation']), ((1, 2), 0))

    def test_unit_days_from_events_that_began_before_the_members_first(self):
        # Someone else's operation, in one entry from the 8th to the 12th.
        self.make_event('operation', when(2024, 1, 8), attended=[self.other], hours=100)
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'operation'), (0, 3))

    def test_only_do_weeks(self):
        DoAvailable.objects.create(member=self.member, year=2024, quarter=1, week=3, assigned=True)
        self.make_event('training', when(2024, 2, 10), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual((rows['total'].do_days, self.days(rows['total'], 'training')), (1, (0, 1)))
        self.assertEqual(member_activity(self.member, NOW)['table']['columns'][:2], ['Operations', 'DO wks'])

    def test_username_case(self):
        self.member.username = 'Ann'
        self.member.save()
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='ann')
        self.assertEqual(self.years()['2024'].led_days['training'], 1)

    def test_counts_start_at_first_day(self):
        self.make_event('training', when(2022, 3, 1), attended=[self.other])
        self.make_event('training', when(2023, 3, 1), attended=[self.other])
        self.make_event('training', when(2023, 9, 1), attended=[self.member])
        self.make_event('training', when(2024, 2, 1), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual([(r.period, self.days(r, 'training')) for r in rows['years']],
                         [(2023, (1, 1)), (2024, (0, 1))])
        self.assertEqual(self.days(rows['total'], 'training'), (1, 2))
        # Months run from the first month attended to this one.
        self.assertEqual([r.period for r in rows['months']][::9], [(2023, 9), (2024, 6)])
        # Ten months are too many to name each on the chart: the year and the quarters are.
        measures, (years, months), _ = self.chart_asked_for()
        self.assertEqual([p['short'] for p in months['periods']], ['', 'Oct', '', '', "'24", '', '', 'Apr', '', ''])
        self.assertEqual(measures[0]['title'], 'Days attended / unit active days, by type, 2023 to 2024')

    def test_counts_stop_at_last_day_for_alumni(self):
        alum = self.make_member('Cat', 'MA')
        self.make_event('meeting', when(2022, 5, 1), attended=[alum])
        self.make_event('meeting', when(2022, 8, 1), attended=[alum])
        self.make_event('meeting', when(2023, 5, 1), attended=[self.other])
        rows = activity_rows(alum, NOW)
        self.assertEqual([(r.period, self.days(r, 'meeting')) for r in rows['years']], [(2022, (2, 2))])
        self.assertEqual(len(rows['months']), 4)


class EntryLedTestCase(TestCase):
    def test_who_led(self):
        # On an operation, the OL flag in the field; an entry flagged AHC as well is out of the field.
        self.assertEqual([entry_led('operation', ol, in_field, named) for ol, in_field, named in
                          [(True, True, False), (True, False, False), (False, True, True)]], [True, False, False])
        # On any other event, the OL flag or a name in the leaders text.
        self.assertEqual([entry_led('training', ol, in_field, named) for ol, in_field, named in
                          [(True, True, False), (False, True, True), (False, True, False)]], [True, True, False])


class EventsAttendedTestCase(ActivityTestCase):
    def events(self, event_type='operation'):
        year = self.years()['2024']
        return year.events[event_type], year.unit_events[event_type]

    def test_an_event_counts_once_on_the_day_it_started(self):
        # Noon on 31 December 2023 for 30 hours: days in two years, one event in the first.
        self.make_event('training', when(2023, 12, 31), attended=[self.member], hours=30)
        years = self.years()
        self.assertEqual((years['2023'].events['training'], years['2024'].events['training']), (1, 0))
        self.assertEqual((years['2023'].days['training'], years['2024'].days['training']), (1, 1))

    def test_unit_events_are_those_with_a_member_out(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other])
        self.make_event('operation', when(2024, 3, 10), ahc=[self.other])          # called off
        self.make_event('operation', when(2024, 4, 10), attended=[self.make_member('Gus', 'G')])
        self.assertEqual(self.events(), (1, 2))

    def test_unit_events_logged_only_for_days_after_today_are_not_counted_yet(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        # A training that has started, with the other member's times typed a year ahead.
        event = self.make_event('training', when(2024, 2, 10))
        Participant.objects.create(period=event.period_set.first(), member=self.other,
                                   en_route_at=when(2025, 2, 10), return_home_at=when(2025, 2, 10) + timedelta(hours=4))
        self.assertEqual(self.events('training'), (1, 1))

    def test_unpublished_events_count(self):
        # Published puts an event on the calendars; the time logged on one that is not counts the same.
        self.make_event('operation', when(2024, 1, 10), attended=[self.member])
        unpublished = self.make_event('operation', when(2024, 2, 10), attended=[self.member, self.other])
        Event.objects.exclude(pk=unpublished.pk).update(published=True)
        self.assertEqual(self.events(), (2, 2))
        self.assertEqual(self.years()['2024'].days['operation'], 2)
        self.assertEqual(member_latest(self.member, NOW)[0]['event'], unpublished)

    def test_ahc_only_and_ol_events(self):
        self.make_event('operation', when(2024, 1, 10), ahc=[self.member])         # called off
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ol=[self.member])
        year = self.years()['2024']
        # The operation attended as AHC is a unit event, for this member.
        self.assertEqual(self.events(), (2, 2))
        self.assertEqual((year.ol_events, year.ahc_events), (1, 1))

    def test_leading_counts_once_an_event(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='Ann (TL)', hours=30)
        year = self.years()['2024']
        self.assertEqual((year.led_events['training'], year.led_days['training']), (1, 2))

    def test_the_longer_username_is_the_leader(self):
        self.member.username = 'lee'
        self.member.save()
        self.other.username = 'ann lee'
        self.other.save()
        self.make_event('training', when(2024, 1, 10), attended=[self.member, self.other], leaders='Ann Lee (TL)')
        self.assertEqual(self.years()['2024'].led_events['training'], 0)
        self.assertEqual(activity_rows(self.other, NOW)['total'].led_events['training'], 1)


class ReportedEventsTestCase(ActivityTestCase):
    """Test and demonstration events, and operations never used, are left out of every report."""

    def titled(self, title, *args, **kwargs):
        event = self.make_event(*args, **kwargs)
        Event.objects.filter(pk=event.pk).update(title=title)
        return Event.objects.get(pk=event.pk)

    def test_test_and_demo_events_are_left_out(self):
        self.titled('Ropes', 'training', when(2024, 1, 10), attended=[self.member])
        for title in ('TEST', '[radio] Test Event', 'test', 'Demo Event - Somewhere', 'Demo Events day'):
            self.titled(title, 'training', when(2024, 2, 10), attended=[self.member])
        # Only a title that is a test or a demonstration: these are training.
        for title in ('Testing anchors', 'Test event prep', 'Rope test'):
            self.titled(title, 'training', when(2024, 3, 10), attended=[self.member])
        total = activity_rows(self.member, NOW)['total']
        self.assertEqual((total.events['training'], total.days['training']), (4, 2))
        # Nor do they make the unit active.
        self.assertEqual(self.days(self.years()['2024'], 'training'), (2, 2))
        self.assertEqual(sorted(p.period.event.title for p in member_entries(self.member)),
                         ['Rope test', 'Ropes', 'Test event prep', 'Testing anchors'])
        self.titled('Test', 'meeting', when(2024, 5, 10), attended=[self.member])
        self.assertNotIn('event', self.latest()['Meeting'])

    def test_operations_never_used_are_left_out(self):
        # Begun once pages were recorded, with no page, nobody listed and no time: never used.
        unused = self.titled('Ridge rescue', 'operation', when(2024, 3, 10))
        # Its title says it was a heads-up, which may have gone by email: kept, as heads-up only.
        warned = self.titled("Hollow Creek search (head's up)", 'operation', when(2024, 4, 10))
        # Begun before pages were recorded: kept, as nothing can tell.
        early = self.titled('Old search', 'operation', when(2016, 8, 8))
        # Titled as a heads-up, but begun before pages told one from a callout: kept, and called off.
        untold = self.titled('Heads up: search', 'operation', when(2018, 5, 10))
        # A page sent, though nobody was listed: used, and called off.
        paged = self.titled('Gully search', 'operation', when(2024, 5, 10))
        self.paged(paged, 'Available?')
        self.assertEqual(self.not_run(), {warned.id: 'heads_up', early.id: 'called_off', untold.id: 'called_off',
                                          paged.id: 'called_off'})
        self.assertNotIn(unused, reported_events())
        self.assertIn('Events left out', dict(glossary()))

    def test_operations_are_left_out_as_never_used_from_9_august_2016_in_local_time(self):
        before = self.titled('Search', 'operation', datetime(2016, 8, 9, 3, 0, tzinfo=dt_timezone.utc))   # 8pm on the 8th
        after = self.titled('Search', 'operation', datetime(2016, 8, 9, 7, 30, tzinfo=dt_timezone.utc))   # 00:30 on the 9th
        self.assertIn(before, reported_events())
        self.assertNotIn(after, reported_events())

    def test_a_heads_up_title_says_heads_up(self):
        # "heads up", "heads-up" or "head's up", in any case, as a word: an operation never used that is
        # titled so is kept, as heads-up only; any other title leaves it out.
        for title in ('Heads up: search', 'HEADS-UP search', "Search (head's up)", 'heads - up'):
            self.assertIn(self.titled(title, 'operation', when(2024, 3, 10)), reported_events(), title)
        for title in ('Headsup search', 'Head up the canyon', 'Spearheads up the trail', 'Heads upstream'):
            self.assertNotIn(self.titled(title, 'operation', when(2024, 3, 10)), reported_events(), title)


class OverlappingTimeTestCase(ActivityTestCase):
    """Time a member logged twice, on two periods or two events at once, counts once in their hours, for
    the one that began first; days count once anyway."""

    def entry(self, event, start, hours, period=None):
        Participant.objects.create(period=period or event.period_set.first(), member=self.member,
                                   en_route_at=start, return_home_at=start + timedelta(hours=hours))

    def test_time_logged_twice_counts_once(self):
        # A training from 1pm to 5pm and a meeting from 3pm to 6pm the same day: 5 hours, not 7.
        training, meeting = self.make_event('training', when(2024, 3, 10)), self.make_event('meeting', when(2024, 3, 10))
        self.entry(training, when(2024, 3, 10), 4)
        self.entry(meeting, when(2024, 3, 10) + timedelta(hours=2), 3)
        total = activity_rows(self.member, NOW)['total']
        self.assertEqual((total.hours['training'], total.hours['meeting'], total.all_hours), (4, 1, 5))
        self.assertEqual((total.days['training'], total.days['meeting'], total.all_days), (1, 1, 1))
        # Each row in the lists shows what it logged: what counts, then what is left out, here counted above.
        participants = member_entries(self.member)
        count_entry_days(participants, NOW)
        self.assertEqual([(p.counted_hours, p.left_out_hours) for p in participants], [(4, 0), (1, 2)])
        # Two periods of one operation, 8am to 4pm and noon to 8pm: 12 hours.
        operation = self.make_event('operation', when(2024, 4, 10))
        self.entry(operation, when(2024, 4, 10) - timedelta(hours=5), 8)
        self.entry(operation, when(2024, 4, 10) - timedelta(hours=1), 8, Period.objects.create(event=operation, position=2))
        self.assertEqual(activity_rows(self.member, NOW)['total'].hours['operation'], 12)

    def test_of_time_logged_twice_the_span_that_began_first_keeps_it(self):
        # Of two that began together, the one given first, as the lists order them (member_entries).
        self.assertEqual(first_claims([(10, 14), (10, 12)]), [(10, 14), None])
        # A span inside another leaves nothing to a third that is inside the first too.
        self.assertEqual(first_claims([(0, 10), (2, 4), (5, 8)]), [(0, 10), None, None])
        self.assertEqual(first_claims([(0, 4), (2, 6), (8, 9)]), [(0, 4), (4, 6), (8, 9)])

    def test_the_first_to_begin_keeps_the_time_whatever_its_event_s_date(self):
        # The meeting is listed first (its event starts earlier) but its time began later.
        meeting = self.make_event('meeting', when(2024, 3, 9))
        training = self.make_event('training', when(2024, 3, 10))
        self.entry(meeting, when(2024, 3, 10) + timedelta(hours=2), 3)
        self.entry(training, when(2024, 3, 10), 4)
        hours = activity_rows(self.member, NOW)['total'].hours
        self.assertEqual((hours['training'], hours['meeting']), (4, 1))


class EntryDaysTestCase(ActivityTestCase):
    def test_an_event_still_to_start_counts_nothing_whatever_its_times(self):
        ahead = self.make_event('training', NOW + timedelta(days=3))
        Participant.objects.create(period=ahead.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 1), return_home_at=when(2024, 6, 1) + timedelta(hours=4))
        self.assertIsNone(activity_rows(self.member, NOW))
        participants = member_entries(self.member)
        count_entry_days(participants, NOW)
        # The list shows its hours, left out, in parentheses.
        self.assertEqual([(p.days, p.counted_hours, p.left_out_hours) for p in participants], [(0, 0, 4)])

    def test_an_entry_across_midnight_shows_its_own_hours(self):
        # 20:13 to 23:46 the next day: 3.78 hours and 23.77, which add up in floating point to just
        # under the entry's 27.55, and would show as 27.5 where the entry holds 27.55, shown as 27.6.
        event = self.make_event('training', when(2024, 1, 9))
        start = datetime(2024, 1, 10, 4, 13, tzinfo=dt_timezone.utc)       # 20:13 PST on 9 January
        Participant.objects.create(period=event.period_set.first(), member=self.member,
                                   en_route_at=start, return_home_at=start + timedelta(hours=27, minutes=33))
        participants = member_entries(self.member)
        count_entry_days(participants, NOW)
        self.assertEqual((participants[0].days, participants[0].counted_hours), (2, participants[0].hours))
        # Nor do times to the microsecond, whose hours round at the sixth decimal:
        # 06:57 to 20:08:30.3666 is 13.1917685 hours.
        start = datetime(2015, 2, 7, 14, 57, tzinfo=dt_timezone.utc)
        participants[0].en_route_at = start
        participants[0].return_home_at = start + timedelta(hours=13, minutes=11, seconds=30, microseconds=366600)
        count_entry_days(participants, NOW)
        self.assertEqual((participants[0].days, participants[0].left_out_hours), (1, 0))

    def test_days_of_each_entry(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member], hours=30)
        self.make_event('meeting', when(2024, 1, 11), attended=[self.member])
        self.make_event('meeting', when(2024, 2, 10), attended=[self.other], no_time=[self.member])
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        self.make_event('operation', when(2024, 4, 10), ahc=[self.member])          # called off; the AHC's day counts
        self.make_event('training', when(2024, 5, 1), attended=[self.member], hours=24 * 8)   # a slip: one day
        self.make_event('training', when(2024, 7, 1), attended=[self.member])                  # not yet happened
        participants = list(Participant.objects.filter(member=self.member)
                            .select_related('period__event').order_by('period__event__start_at'))
        count_entry_days(participants, NOW)
        self.assertEqual([p.days for p in participants], [2, 1, 0, 1, 1, 1, 0])
        # Hours that count towards no total are marked: the slip, and time logged ahead of the event.
        # And the meeting of the 11th, all inside the training's 30 hours, which count once, for the training.
        self.assertEqual([bool(p.left_out_hours) for p in participants], [False, True] + [False] * 3 + [True, True])
        # So is time that ends before it starts.
        backwards = participants[1]
        backwards.return_home_at = backwards.en_route_at - timedelta(hours=3)
        count_entry_days([backwards], NOW)
        self.assertEqual((backwards.days, backwards.left_out_hours), (0, -3))
        # The second day of the training is also the meeting's day: the total counts it once.
        self.assertEqual(activity_rows(self.member, NOW)['total'].all_days, 5)

    def test_entries_loaded_once_serve_the_lists_and_the_totals(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member], hours=30)
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        self.make_event('training', when(2024, 7, 1), attended=[self.member])       # not yet happened
        entries = member_entries(self.member)
        self.assertEqual(len(entries), 3)
        with self.assertNumQueries(0):
            count_entry_days(entries, NOW)
        # Given them, the totals are the same and the member's entries are not read again.
        self.assertEqual(activity_rows(self.member, NOW, entries), activity_rows(self.member, NOW))
        with CaptureQueriesContext(connection) as without:
            activity_rows(self.member, NOW)
        with CaptureQueriesContext(connection) as given:
            activity_rows(self.member, NOW, entries)
        self.assertEqual(len(given), len(without) - 1)

    def test_each_entry_shows_what_the_totals_count(self):
        # A training that has started, with times typed for five days ahead: nothing yet.
        ahead = self.make_event('training', when(2024, 6, 10))
        Participant.objects.create(period=ahead.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 20), return_home_at=when(2024, 6, 20) + timedelta(hours=6))
        # One under way, 1pm on the 14th to 1pm on the 16th: the 14th and today, with their 11 and 24 hours.
        under_way = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=under_way.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 16))
        participants = list(Participant.objects.filter(member=self.member)
                            .select_related('period__event').order_by('period__event__start_at'))
        count_entry_days(participants, NOW)
        self.assertEqual([(p.days, p.counted_hours, p.left_out_hours) for p in participants],
                         [(0, 0, 6), (2, 35, 13)])
        total = activity_rows(self.member, NOW)['total']
        self.assertEqual((total.days['training'], total.hours['training']), (2, 35))


class CountedAgainstTheRulesTestCase(ActivityTestCase):
    """activity_rows against a reading of the glossary's rules written out
    the long way, minute by minute, on random members, events and times, at
    three times of day: early morning and evening in UTC fall on the day
    before or the same local day."""
    NOWS = [datetime(2024, 6, 15, h, m, tzinfo=dt_timezone.utc) for h, m in ((3, 0), (7, 30), (20, 0))]

    def scenario(self, rnd):
        """Random events from November 2023 (the clocks go back on the 5th, forward on 10 March) to past the
        last NOW, some all-day from local midnight, some in the evening, with entries short and long."""
        guest, alum = self.make_member('Gus', 'G'), self.make_member('Al', 'MA')
        people = [self.member, self.member, self.other, guest, alum]
        for _ in range(14):
            day = date(2023, 11, 1) + timedelta(days=rnd.randrange(235))
            hour = rnd.choice([0, 0, 8, 13, 19.5, 23])
            start = timezone.make_aware(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour))
            event = Event.objects.create(type=rnd.choice(TYPES), title='Event', location='Here', leaders='',
                                         start_at=start, finish_at=start + timedelta(hours=rnd.choice([3, 30])))
            periods = [event.period_set.first()]
            if rnd.random() < 0.3:
                periods.append(Period.objects.create(event=event, position=2))
            for member in rnd.sample(people, rnd.randrange(1, 4)):
                begin = start + timedelta(hours=rnd.choice([-2, 0, 0, 3, 30]))
                end = begin + timedelta(minutes=rnd.choice([0, 30, 90, 120, 180, 660, 720, 780, 1560, 2940,
                                                            7 * 1440, 7 * 1440 + 60, 9 * 1440]))
                times = ({'en_route_at': begin, 'return_home_at': end} if rnd.random() < 0.7
                         else {'signed_in_at': begin, 'signed_out_at': end})
                Participant.objects.create(period=rnd.choice(periods), member=member, ahc=rnd.random() < 0.25,
                                           ol=rnd.random() < 0.2, **(times if rnd.random() < 0.9 else {}))

    @staticmethod
    def span(p, tz):
        """An entry's logged time as (start, end), the long way; None without it, or for over 7 local days."""
        if p.en_route_at and p.return_home_at:
            start, end = p.en_route_at, p.return_home_at
        else:
            start, end = p.signed_in_at, p.signed_out_at
        if not start or not end or end <= start:
            return None
        if end.astimezone(tz).replace(tzinfo=None) - start.astimezone(tz).replace(tzinfo=None) > timedelta(days=7):
            return None
        return start, end

    def counted_days(self, p, tz, covered=frozenset()):
        """{local day: hours} for an entry, the long way, minute by minute. The minutes in `covered`, counted
        for an entry that began earlier, are left out of its hours, but not of the days it counts."""
        span = self.span(p, tz)
        if span is None:
            start = p.en_route_at if p.en_route_at and p.return_home_at else p.signed_in_at
            end = p.return_home_at if p.en_route_at and p.return_home_at else p.signed_out_at
            return {start.astimezone(tz).date(): 0} if start and end and end > start else {}
        start, end = span
        minutes, own = {}, {}
        t = start
        while t < end:
            day = t.astimezone(tz).date()
            minutes[day] = minutes.get(day, 0) + 1
            if int(t.timestamp()) // 60 not in covered:
                own[day] = own.get(day, 0) + 1
            t += timedelta(minutes=1)
        fullest = max(minutes, key=minutes.get)
        if sum(minutes.values()) <= 12 * 60:
            days = [fullest]
        else:
            days = [day for day, m in minutes.items() if m >= 2 * 60 or day == fullest]
        counted = dict.fromkeys(days, 0)
        for day, m in own.items():
            counted[day if day in counted else min(counted, key=lambda other: abs((other - day).days))] += m
        return {day: m / 60 for day, m in counted.items()}

    def own_days(self, now, tz):
        """The member's entries' {local day: hours}, by id, with each minute logged twice counted once, for
        the entry whose time began first (then the first in member_entries' order)."""
        mine = list(Participant.objects.filter(member=self.member).select_related('period__event')
                    .order_by('period__event__start_at', 'period__event_id', 'period__position', 'id'))
        claims = sorted((span[0], order) for order, p in enumerate(mine)
                        if p.period.event.start_at <= now and (span := self.span(p, tz)))
        covered, days = set(), {}
        for _, order in claims:
            p = mine[order]
            days[p.id] = self.counted_days(p, tz, frozenset(covered))
            start, end = self.span(p, tz)
            covered |= set(range(int(start.timestamp()) // 60, int(end.timestamp()) // 60))
        return {p.id: days.get(p.id) or self.counted_days(p, tz) for p in mine}

    def expected(self, now, days_of):
        """The member's figures by year, from the rules: {year: (days, active days, events, unit events,
        hours, all days)}, each but all days {type: figure}."""
        tz = timezone.get_current_timezone()
        today = now.astimezone(tz).date()
        own_days, ahc_days = {t: set() for t in TYPES}, set()
        own_events, hours = {t: {} for t in TYPES}, {t: defaultdict(float) for t in TYPES}
        unit_days, unit_events = {t: set() for t in TYPES}, {t: {} for t in TYPES}
        own = self.own_days(now, tz)
        for p in Participant.objects.select_related('period__event', 'member'):
            event = p.period.event
            if event.start_at > now:
                continue
            days = days_of[p.id]
            ahc = event.type == 'operation' and p.ahc
            if p.member == self.member:
                days = own[p.id]
                mine = {day: h for day, h in days.items() if day <= today}
                (ahc_days if ahc else own_days[event.type]).update(mine)
                for day, h in mine.items():
                    hours[event.type][day] += h
                if mine:
                    own_events[event.type][event.id] = timezone.localtime(event.start_at).date()
            if p.member.status not in Member.GUESTS and not ahc:
                unit_days[event.type].update(days)
                if any(day <= today for day in days):
                    unit_events[event.type][event.id] = event.start_at
        own_days['operation'] |= ahc_days
        involved = set().union(*own_days.values()) | {d for e in own_events.values() for d in e.values()}
        if not involved:
            return None
        first = min(involved)
        start = timezone.make_aware(datetime.combine(first, datetime.min.time()))
        active = {t: unit_days[t] | own_days[t] for t in TYPES}
        unit = {t: {**{e: timezone.localtime(s).date() for e, s in unit_events[t].items() if s >= start},
                    **own_events[t]} for t in TYPES}

        def year_of(days, y):
            return sum(1 for day in days if first <= day <= today and day.year == y)
        return {y: ({t: year_of(own_days[t], y) for t in TYPES}, {t: year_of(active[t], y) for t in TYPES},
                    {t: year_of(own_events[t].values(), y) for t in TYPES},
                    {t: year_of(unit[t].values(), y) for t in TYPES},
                    {t: round(sum(h for day, h in hours[t].items() if first <= day <= today and day.year == y), 6)
                     for t in TYPES},
                    year_of(set().union(*own_days.values()), y))
                for y in range(first.year, today.year + 1)}

    def test_activity_rows_follow_the_rules(self):
        tz = timezone.get_current_timezone()
        for seed in range(8):
            Event.objects.all().delete()
            Member.objects.exclude(pk__in=[self.member.pk, self.other.pk]).delete()
            self.scenario(random.Random(seed))
            days_of = {p.id: self.counted_days(p, tz) for p in Participant.objects.all()}
            for now in self.NOWS:
                rows = activity_rows(self.member, now)
                got = rows and {r.period: (r.days, r.active_days, r.events, r.unit_events,
                                            {t: round(r.hours[t], 6) for t in TYPES}, r.all_days)
                                for r in rows['years']}
                self.assertEqual(got, self.expected(now, days_of), 'seed {}, now {}'.format(seed, now))
