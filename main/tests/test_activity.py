import random
from collections import defaultdict
from unittest import mock
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from main.lib.activity import glossary, member_activity
from main.lib.counting import (MAX_ENTRY, TYPES, NotRun, activity_rows, count_entry_days, day_hours, entry_hours, entry_led,
                               hours_by_local_day, member_entries, member_latest, operations_not_run,
                               operations_that_ran, reported_events, unit_since)
from main.models import DoAvailable, Event, Member, Message, Participant, Period, RsvpTemplate

NOW = datetime(2024, 6, 15, 20, 0, tzinfo=dt_timezone.utc)


def when(year, month, day):
    """20:00 UTC, the middle of the day in Pacific time (noon in winter, 1pm in
    summer), so short events stay within one local day."""
    return datetime(year, month, day, 20, 0, tzinfo=dt_timezone.utc)


class ActivityTestCase(TestCase):
    def setUp(self):
        self.member = self.make_member('Ann', 'FM')
        self.other = self.make_member('Bob', 'FM')

    def make_member(self, name, status):
        return Member.objects.create(first_name=name, last_name='Test',
                                     username=name.lower(), status=status)

    def make_event(self, event_type, start, attended=(), no_time=(), ahc=(), ol=(), hours=4,
                   leaders=''):
        """Create a one-period event. `attended` and `ol` members log `hours`
        (the `ol` ones flagged OL); `no_time` members are listed without times;
        `ahc` members log two hours as AHC."""
        event = Event.objects.create(type=event_type, title='Event', location='Here', leaders=leaders,
                                     start_at=start, finish_at=start + timedelta(hours=hours))
        # Saving an event creates its first period.
        period = event.period_set.first() or Period.objects.create(event=event, position=1)
        for member in list(attended) + list(ol):
            Participant.objects.create(period=period, member=member, ol=member in ol,
                                       en_route_at=start,
                                       return_home_at=start + timedelta(hours=hours))
        for member in no_time:
            Participant.objects.create(period=period, member=member)
        for member in ahc:
            Participant.objects.create(period=period, member=member, ahc=True, en_route_at=start,
                                       return_home_at=start + timedelta(hours=2))
        return event

    def years(self, member=None):
        return {str(row['year']): row for row in activity_rows(member or self.member, NOW)['years']}

    def days(self, row, event_type):
        """(days attended, unit active days)"""
        return row['days'][event_type], row['active_days'][event_type]

    def chart_asked_for(self, member=None):
        """What the report gives the chart component to draw, not what that makes
        of it: (measures, views, options), as passed to charts.share_panels."""
        with mock.patch('main.lib.activity.charts.share_panels') as share_panels:
            member_activity(member or self.member, NOW)
        (measures, views), options = share_panels.call_args
        return measures, views, options

    def panel(self, label, view=0, member=None):
        """One panel as the report asks for it: {'label', 'key', 'cells'}, each
        cell a column for days, events and hours with its parts and its figures."""
        _, views, _ = self.chart_asked_for(member)
        return next(series for series in views[view]['series'] if series['label'] == label)

    def latest(self, member=None):
        return {i['label']: i for i in member_latest(member or self.member, NOW)}

    def not_run(self):
        """Why each operation that did not run by NOW did not: {id: 'heads_up' or 'called_off'}."""
        return {event_id: not_run.why for event_id, not_run in operations_not_run(NOW, operations_that_ran(NOW)).items()}


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
        self.assertEqual(year['all_hours'], 8)

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
        self.assertEqual((year['all_days'], year['all_active_days'], year['all_hours']), (2, 3, 8))
        # Each day is counted under the first type attended on it.
        self.assertEqual(year['first_days'], {'operation': 0, 'training': 2, 'meeting': 0, 'community': 0})

    def test_called_off_operations(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member])
        # Members listed, and none logged time.
        self.make_event('operation', when(2024, 2, 10), no_time=[self.member, self.other])
        # Only the AHC logged time: called off, but the AHC did the work.
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member], no_time=[self.other])
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (2, 2))
        self.assertEqual(year['duty'], {'ol': 0, 'ahc': 1, 'do': 0})
        self.assertEqual(year['all_hours'], 6)
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
        self.assertEqual((year['duty']['ol'], year['hours']['ol']), (1, 4))

    def test_days_as_ahc_are_days_attended(self):
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        # Listed as AHC without times: no duty.
        event = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True)
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (1, 2))
        self.assertEqual((year['duty']['ahc'], year['hours']['ahc'], year['all_days']), (1, 2, 1))

    def test_ahc_for_one_period_and_in_the_field_for_another(self):
        event = self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member])
        second = Period.objects.create(event=event, position=2)
        for member in (self.member, self.other):
            Participant.objects.create(period=second, member=member, en_route_at=when(2024, 1, 11),
                                       return_home_at=when(2024, 1, 11) + timedelta(hours=4))
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'operation'), (2, 2))
        self.assertEqual(year['duty']['ahc'], 1)
        # AHC and in the field on the same day is one day, in the field.
        third = Period.objects.create(event=event, position=3)
        Participant.objects.create(period=third, member=self.member, ahc=True, en_route_at=when(2024, 1, 11),
                                   return_home_at=when(2024, 1, 11) + timedelta(hours=2))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year['duty']['ahc']), ((2, 2), 1))

    def test_ahc_flag_means_nothing_off_operations(self):
        event = self.make_event('training', when(2024, 1, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 1, 10),
                                   return_home_at=when(2024, 1, 10) + timedelta(hours=5))
        self.make_event('operation', when(2024, 2, 10), attended=[self.member], hours=3)
        year = self.years()['2024']
        self.assertEqual(self.days(year, 'training'), (1, 1))
        self.assertEqual((year['hours']['training'], year['hours']['operation'], year['hours']['ahc']), (5, 3, 0))
        # A training only someone flagged AHC logged time on still ran.
        self.make_event('training', when(2024, 3, 10), ahc=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'training'), (2, 2))

    def test_ahc_time_before_and_after_everything_else_is_kept(self):
        # AHC time on called-off operations, before the first and after the last other event.
        self.make_event('operation', when(2023, 1, 10), ahc=[self.member])
        self.make_event('meeting', when(2023, 6, 10), attended=[self.member])
        self.make_event('operation', when(2024, 1, 10), ahc=[self.member])
        rows = activity_rows(self.member, NOW)
        self.assertEqual((rows['total']['all_days'], rows['total']['all_hours']), (3, 8))
        alum = self.make_member('Cat', 'MA')
        self.make_event('meeting', when(2023, 6, 10), attended=[alum])
        self.make_event('operation', when(2024, 1, 10), ahc=[alum])
        self.assertEqual(activity_rows(alum, NOW)['total']['all_hours'], 6)

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
        self.assertEqual((year['events']['training'], year['unit_events']['training']), (1, 1))

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
        self.assertEqual([(y, years[y]['events']['training'], years[y]['unit_events']['training'], years[y]['days']['training'])
                          for y in ('2023', '2024')], [('2023', 2, 3, 1), ('2024', 0, 0, 1)])

    def test_the_unit_counts_from_sign_in_times_alone(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        signed = self.make_event('training', when(2024, 2, 10))
        Participant.objects.create(period=signed.period_set.first(), member=self.other,
                                   signed_in_at=when(2024, 2, 10), signed_out_at=when(2024, 2, 10) + timedelta(hours=3))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'training'), year['unit_events']['training']), ((1, 2), 2))

    def test_another_event_on_the_members_first_day_is_a_unit_event(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        self.make_event('training', when(2024, 1, 10) - timedelta(hours=3), attended=[self.other])
        # An all-day event starts at local midnight, the very start of the member's first day.
        self.make_event('meeting', timezone.make_aware(datetime(2024, 1, 10)), attended=[self.other])
        year = self.years()['2024']
        self.assertEqual((year['events']['training'], year['unit_events']['training']), (1, 2))
        self.assertEqual(year['unit_events']['meeting'], 1)

    def test_a_unit_event_after_the_first_day_counts_whenever_its_times_were_typed(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member])
        # An event of March whose only times are typed for January: a slip, but the event ran, in March.
        march = self.make_event('training', when(2024, 3, 10))
        Participant.objects.create(period=march.period_set.first(), member=self.other,
                                   en_route_at=when(2023, 12, 1), return_home_at=when(2023, 12, 1) + timedelta(hours=4))
        self.assertEqual(self.years()['2024']['unit_events']['training'], 2)

    def test_someone_no_longer_a_member_is_counted_to_their_last_day(self):
        # A former member, and a guest: the unit's later days are not theirs to have attended.
        for status in ('MN', 'G'):
            gone = self.make_member('Dan' + status, status)
            self.make_event('training', when(2024, 1, 10), attended=[gone])
            self.make_event('training', when(2024, 3, 10), attended=[self.other])
            rows = activity_rows(gone, NOW)
            self.assertEqual(self.days(rows['total'], 'training'), (1, 1), status)
            self.assertEqual([m['month'] for m in rows['months']], [(2024, 1)], status)
            Event.objects.all().delete()

    def test_an_operation_flagged_ahc_and_ol_is_attended_as_ahc(self):
        operation = self.make_event('operation', when(2024, 1, 10), attended=[self.other], ahc=[self.member])
        Participant.objects.filter(period__event=operation, member=self.member).update(ol=True)
        year = self.years()['2024']
        self.assertEqual((year['event_duty'], year['duty']['ol'], year['duty']['ahc'], year['hours']['ol']),
                         ({'ol': 0, 'ahc': 1}, 0, 1, 0))

    def test_ol_flag_off_operations_is_leading(self):
        self.make_event('training', when(2024, 1, 10), ol=[self.member])
        year = self.years()['2024']
        self.assertEqual((year['led_days']['training'], year['duty']['ol']), (1, 0))

    def test_do_weeks(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        for quarter, week in ((1, 3), (2, 1), (4, 1)):   # the last has not started
            DoAvailable.objects.create(member=self.member, year=2024, quarter=quarter, week=week,
                                       assigned=True)
        DoAvailable.objects.create(member=self.member, year=2024, quarter=1, week=5, available=True)
        self.assertEqual(self.years()['2024']['duty']['do'], 2)

    def test_ahc_hours_are_named_in_the_key_without_an_ahc_day(self):
        # AHC in the morning and in the field that afternoon: a day in the field, with AHC hours.
        operation = self.make_event('operation', when(2024, 3, 10), attended=[self.member])
        Participant.objects.create(period=operation.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 10) - timedelta(hours=4),
                                   return_home_at=when(2024, 3, 10) - timedelta(hours=2))
        self.assertEqual(self.years()['2024']['duty']['ahc'], 0)
        panel = self.panel('Operations')
        self.assertEqual([label for _, label in panel['key']], ['Other attendance', 'as AHC'])
        days, events, hours = panel['cells'][0]
        self.assertEqual(hours['tip'], ['2024', ('6.0', 'hours'), ('2.0', 'as AHC')])
        # In the field on it too, the operation is not one attended as AHC only.
        self.assertEqual(events['tip'], ['2024', ('1 of 1', 'event')])

    def test_hours_go_to_the_days_they_fell_on(self):
        # 8pm on 31 December to 4pm on 1 January, Pacific time: a day in each year.
        start = datetime(2024, 1, 1, 4, 0, tzinfo=dt_timezone.utc)
        self.make_event('operation', start, ol=[self.member], hours=20)
        years = self.years()
        self.assertEqual([(years[y]['days']['operation'], years[y]['hours']['operation'], years[y]['hours']['ol'])
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
        self.assertEqual(activity_rows(self.member, start)['total']['duty']['do'], 1)
        # The same whatever timezone the time now is given in: 8am Pacific is 3pm UTC.
        half_past_seven = (start - timedelta(minutes=30)).astimezone(dt_timezone.utc)
        self.assertIsNone(activity_rows(self.member, half_past_seven))
        self.assertEqual(activity_rows(self.member, half_past_seven + timedelta(hours=1))['total']['duty']['do'], 1)

    def test_time_entered_for_a_day_after_today_is_not_counted_yet(self):
        event = self.make_event('training', when(2024, 6, 1), attended=[self.member])
        Participant.objects.filter(period__event=event).update(
            en_route_at=when(2025, 6, 1), return_home_at=when(2025, 6, 1) + timedelta(hours=4))
        self.assertIsNone(activity_rows(self.member, NOW))
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        rows = activity_rows(self.member, NOW)
        self.assertEqual(([r['year'] for r in rows['years']], rows['total']['all_days']), ([2024], 1))

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
        self.assertEqual(year['led_days'], {'operation': 0, 'training': 1, 'meeting': 1, 'community': 1})
        self.assertEqual(year['hours']['led_training'], 4)

    def test_leaders_are_members_whose_username_is_in_the_text(self):
        for leaders, led in (('Ann', 1), ('Bob, ANN', 1), ('Ann (TL), Bob (LL)', 1), ('Bob and Ann', 1),
                             ('Bob & Ann(TL, LL)', 1), ('Bob/Ann; Cy', 1), ('TL: ann', 1),
                             ('Annabel', 0), ('Joann', 0), ('Ann2', 0), ('Bob', 0), ('', 0)):
            Event.objects.all().delete()
            self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders=leaders)
            self.assertEqual(self.years()['2024']['led_days']['training'], led, leaders)

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
        self.assertEqual((year['days']['meeting'], year['days']['community'], year['all_hours']), (1, 8, 4 + 168))
        # Someone whose only entry is a slip still has a report.
        self.assertEqual(activity_rows(self.other, NOW)['total']['all_days'], 2)

    def test_ahc_on_a_called_off_operation(self):
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member], no_time=[self.other])
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year['duty']['ahc']), ((1, 1), 1))

    def test_ahc_days_count_for_the_member_everywhere(self):
        # AHC on a called-off operation, and on a day of an operation when nobody was in the field.
        self.make_event('operation', when(2024, 3, 10), ahc=[self.member])
        event = self.make_event('operation', when(2024, 4, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 4, 12), return_home_at=when(2024, 4, 12) + timedelta(hours=3))
        rows = activity_rows(self.member, NOW)
        year = rows['years'][0]
        self.assertEqual((self.days(year, 'operation'), year['duty']['ahc']), ((2, 3), 2))
        self.assertEqual((year['all_days'], year['all_active_days']), (2, 3))
        months = {r['month']: r for r in rows['months']}
        self.assertEqual(self.days(months[(2024, 3)], 'operation'), (1, 1))
        self.assertEqual((months[(2024, 3)]['all_days'], months[(2024, 3)]['all_active_days']), (1, 1))
        self.assertEqual(self.days(months[(2024, 4)], 'operation'), (1, 2))
        self.assertEqual(self.panel('All')['cells'][0][0]['tip'], ['2024', ('2 of 3', 'days')])

    def test_ahc_entry_too_long_to_be_right(self):
        event = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=event.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 30))
        year = self.years()['2024']
        self.assertEqual((self.days(year, 'operation'), year['duty']['ahc'], year['hours']['ahc']), ((1, 1), 1, 0))

    def test_time_logged_before_the_event(self):
        # Times typed a month before the event's date: the window starts at the time
        # logged, and the unit's days are fetched from there.
        event = self.make_event('training', when(2024, 1, 20))
        for member in (self.member, self.other):
            Participant.objects.create(period=event.period_set.first(), member=member,
                                       en_route_at=when(2023, 12, 20), return_home_at=when(2023, 12, 20) + timedelta(hours=4))
        self.make_event('training', when(2023, 12, 28), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual([(r['year'], self.days(r, 'training')) for r in rows['years']],
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
        self.assertEqual((self.days(year, 'operation'), year['hours']['operation']), ((2, 2), 30))
        # The member who made the slip: one day, no hours.
        year = self.years(self.other)['2024']
        self.assertEqual((self.days(year, 'operation'), year['hours']['operation']), ((1, 2), 0))

    def test_unit_days_from_events_that_began_before_the_members_first(self):
        # Someone else's operation, in one entry from the 8th to the 12th.
        self.make_event('operation', when(2024, 1, 8), attended=[self.other], hours=100)
        self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        self.assertEqual(self.days(self.years()['2024'], 'operation'), (0, 3))

    def test_only_do_weeks(self):
        DoAvailable.objects.create(member=self.member, year=2024, quarter=1, week=3, assigned=True)
        self.make_event('training', when(2024, 2, 10), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual((rows['total']['duty']['do'], self.days(rows['total'], 'training')), (1, (0, 1)))
        self.assertEqual(member_activity(self.member, NOW)['table']['columns'][:2], ['Operations', 'DO wks'])

    def test_username_case(self):
        self.member.username = 'Ann'
        self.member.save()
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='ann')
        self.assertEqual(self.years()['2024']['led_days']['training'], 1)

    def test_counts_start_at_first_day(self):
        self.make_event('training', when(2022, 3, 1), attended=[self.other])
        self.make_event('training', when(2023, 3, 1), attended=[self.other])
        self.make_event('training', when(2023, 9, 1), attended=[self.member])
        self.make_event('training', when(2024, 2, 1), attended=[self.other])
        rows = activity_rows(self.member, NOW)
        self.assertEqual([(r['year'], self.days(r, 'training')) for r in rows['years']],
                         [(2023, (1, 1)), (2024, (0, 1))])
        self.assertEqual(self.days(rows['total'], 'training'), (1, 2))
        # Months run from the first month attended to this one.
        self.assertEqual([r['month'] for r in rows['months']][::9], [(2023, 9), (2024, 6)])
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
        self.assertEqual([(r['year'], self.days(r, 'meeting')) for r in rows['years']], [(2022, (2, 2))])
        self.assertEqual(len(rows['months']), 4)


class EventLeadersTestCase(ActivityTestCase):
    def named(self, text, *usernames):
        """Those of these usernames a leaders text names, by Event.members_named."""
        return Event.members_named([text], [(username, username) for username in usernames]).get(text, set())

    def test_members_named(self):
        text = 'Ann  Lee (TL), bo diaz and CY NG(LL) / Search and Rescue Team'
        for username in ('ann lee', 'Ann Lee', 'bo diaz', 'cy ng', ' cy  ng ', 'lee', 'team'):
            self.assertEqual(self.named(text, username), {username}, username)
        # Whole words only, and never an empty username.
        for username in ('ann le', 'o diaz', 'sue lee', 'tea', '', ' '):
            self.assertEqual(self.named(text, username), set(), username)
        self.assertEqual(Event.members_named([None, ''], [('ann lee', 1)]), {})
        # Punctuation in a username is matched as written.
        self.assertEqual(self.named("Pat O'Neil-Diaz (TL)", "pat o'neil-diaz"), {"pat o'neil-diaz"})
        self.assertEqual(self.named('Pat O.Neil', "pat o'neil"), set())
        # Many texts are read with one pattern.
        self.assertEqual(Event.members_named(['Ann Lee (TL)', 'Bo Diaz, Ann Lee', 'nobody'], [('ann lee', 1), ('bo diaz', 2)]),
                         {'Ann Lee (TL)': {1}, 'Bo Diaz, Ann Lee': {1, 2}, 'nobody': set()})

    def test_the_event_page_reads_a_text_as_the_reports_do(self):
        # Ignoring case, Python's patterns take a long s for an s and a micro sign for a mu, where lower() does
        # not; read one way, "ſam fox" is matched whole, not linked, and leaves no "fox" for member 2.
        members = [('sam fox', 1), ('fox', 2), ('μike lee', 3), ('lee', 4)]
        for text in ('ſam fox (TL)', 'µike lee (LL)'):
            linked = {id for _, id in Event(leaders=text).leader_parts(members) if id}
            self.assertEqual(linked, Event.members_named([text], members)[text], text)
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
        self.assertEqual(activity_rows(alum, NOW)['total']['led_events']['training'], 1)

    def test_the_longer_username_is_the_one_named(self):
        # Longer by its letters, not its words.
        self.assertEqual(self.named('Ann Lee-Fox (TL)', 'ann lee', 'ann lee-fox'), {'ann lee-fox'})
        # Where two usernames could match at one place, the longer is the one named.
        self.assertEqual(self.named('Ann Lee (TL)', 'lee'), {'lee'})
        self.assertEqual(self.named('Ann Lee (TL)', 'lee', 'ann lee', 'ann'), {'ann lee'})
        # A username ends at a hyphen or an apostrophe too, so one inside another's word is not named.
        self.assertEqual(self.named("Pat O'Neil-Diaz (TL)", 'diaz', "pat o'neil-diaz"), {"pat o'neil-diaz"})
        self.assertEqual(Event(leaders="Pat O'Neil-Diaz (TL)").leader_parts([("pat o'neil-diaz", 1), ('diaz', 2)]),
                         [("Pat O'Neil-Diaz", 1), (' (TL)', None)])
        # Named in its own right elsewhere in the text, the shorter still counts.
        self.assertEqual(self.named('Ann Lee (TL), Lee (LL)', 'lee', 'ann lee'), {'lee', 'ann lee'})
        self.assertEqual(self.named('Lee Fox', 'lee fox', 'lee'), {'lee fox'})

    def test_leader_parts(self):
        event = Event(leaders='Ann Lee (TL), bo diaz and Ann Leeson')
        members = [('ann lee', 1), ('bo diaz', 2), ('ann leeson', 3), ('ann', 4), ('cy ng', 5)]
        self.assertEqual(event.leader_parts(members), [
            ('Ann Lee', 1), (' (TL), ', None), ('bo diaz', 2), (' and ', None), ('Ann Leeson', 3)])
        self.assertEqual(event.leader_parts([]), [('Ann Lee (TL), bo diaz and Ann Leeson', None)])
        # The first username to start in the text wins, before the longer one.
        overlap = Event(leaders='Ann Lee Fox')
        self.assertEqual(overlap.leader_parts([('ann lee', 1), ('lee fox', 2)]), [('Ann Lee', 1), (' Fox', None)])
        self.assertEqual(self.named('Ann Lee Fox', 'ann lee', 'lee fox'), {'ann lee'})
        # Of two usernames that differ only by case or spacing, the first given.
        self.assertEqual(Event(leaders='Ann Lee').leader_parts([('Ann  Lee', 7), ('ann lee', 8)]), [('Ann Lee', 7)])
        self.assertEqual(Event(leaders='').leader_parts(members), [])
        # A letter that matches in any case without lowering to the username stays plain text.
        self.assertEqual(Event(leaders='\u017fam fox').leader_parts([('sam fox', 6)]), [('\u017fam fox', None)])

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
        led = {m: activity_rows(m, NOW)['total']['led_events']['training'] for m in (self.member, self.other)}
        self.assertEqual(led, {self.member: 1, self.other: 0})


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
        return year['events'][event_type], year['unit_events'][event_type]

    def test_an_event_counts_once_on_the_day_it_started(self):
        # Noon on 31 December 2023 for 30 hours: days in two years, one event in the first.
        self.make_event('training', when(2023, 12, 31), attended=[self.member], hours=30)
        years = self.years()
        self.assertEqual((years['2023']['events']['training'], years['2024']['events']['training']), (1, 0))
        self.assertEqual((years['2023']['days']['training'], years['2024']['days']['training']), (1, 1))

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
        self.assertEqual(self.years()['2024']['days']['operation'], 2)
        self.assertEqual(member_latest(self.member, NOW)[0]['event'], unpublished)

    def test_ahc_only_and_ol_events(self):
        self.make_event('operation', when(2024, 1, 10), ahc=[self.member])         # called off
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ol=[self.member])
        year = self.years()['2024']
        # The operation attended as AHC is a unit event, for this member.
        self.assertEqual(self.events(), (2, 2))
        self.assertEqual(year['event_duty'], {'ol': 1, 'ahc': 1})

    def test_leading_counts_once_an_event(self):
        self.make_event('training', when(2024, 1, 10), attended=[self.member], leaders='Ann (TL)', hours=30)
        year = self.years()['2024']
        self.assertEqual((year['led_events']['training'], year['led_days']['training']), (1, 2))

    def test_the_longer_username_is_the_leader(self):
        self.member.username = 'lee'
        self.member.save()
        self.other.username = 'ann lee'
        self.other.save()
        self.make_event('training', when(2024, 1, 10), attended=[self.member, self.other], leaders='Ann Lee (TL)')
        self.assertEqual(self.years()['2024']['led_events']['training'], 0)
        self.assertEqual(activity_rows(self.other, NOW)['total']['led_events']['training'], 1)


class MemberActivityTestCase(ActivityTestCase):
    def test_each_key_names_the_colours_its_panel_draws(self):
        self.make_event('operation', when(2024, 1, 10), ol=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        self.make_event('training', when(2024, 3, 12), attended=[self.member], leaders='Ann (TL)')
        self.make_event('training', when(2024, 3, 14), attended=[self.member])
        self.make_event('meeting', when(2024, 4, 10), attended=[self.member])
        self.make_event('community', when(2024, 5, 10), attended=[self.member])
        _, views, _ = self.chart_asked_for()
        for series in views[0]['series']:
            drawn = {colour for cell in series['cells'] for measure in cell for colour, amount in measure['parts'] if amount}
            self.assertEqual({colour for colour, _ in series['key']}, drawn, series['label'])

    def test_figures_say_days_and_events_by_the_unit_s_count(self):
        # "1 of 2 days": the noun goes with the whole, the 2.
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        self.make_event('training', when(2024, 4, 10), attended=[self.other])
        days, events, _ = self.panel('Trainings')['cells'][0]
        self.assertEqual((days['tip'][1], events['tip'][1]), (('1 of 2', 'days'), ('1 of 2', 'events')))

    def test_the_led_hours_line_is_the_hours_led(self):
        # Of a year's 10 hours of training, the 4 led are picked out.
        self.make_event('training', when(2024, 3, 10), attended=[self.member], leaders='Ann (TL)', hours=4)
        self.make_event('training', when(2024, 4, 10), attended=[self.member], hours=6)
        hours = self.panel('Trainings')['cells'][0][2]
        self.assertEqual(hours['tip'], ['2024', ('10.0', 'hours'), ('4.0', 'as TL or LL')])
        self.assertEqual(hours['parts'], [('1-strong', 4), ('1', 6)])

    def test_figures_show_hours_to_one_decimal_as_the_table_does(self):
        self.make_event('community', when(2024, 1, 10), attended=[self.member], hours=0.5)
        hours = self.panel('Community')['cells'][0][2]['tip']
        self.assertEqual(hours, ['2024', ('0.5', 'hours')])
        self.assertEqual(member_activity(self.member, NOW)['table']['total']['cells'][-1], ('Total', '1 / 0.5 hours'))

    def test_hours_as_ol_and_ahc_alone_leave_no_other_hours(self):
        # Half an hour as OL and forty minutes as AHC: taking both from the total
        # in floating point leaves -1e-16, which the chart would draw below zero.
        self.make_event('operation', when(2024, 1, 10), ol=[self.member], hours=0.5)
        ahc = self.make_event('operation', when(2024, 2, 10), attended=[self.other])
        Participant.objects.create(period=ahc.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 2, 10),
                                   return_home_at=when(2024, 2, 10) + timedelta(minutes=40))
        hours = [cell[2]['parts'] for cell in self.panel('Operations')['cells']]
        self.assertEqual(hours, [[('1-strong', 0.5), ('1', 0), ('1-light', 40 / 60)]])
        self.assertEqual(activity_rows(self.member, NOW)['total']['hours']['other_operation'], 0)

    def test_chart(self):
        self.make_event('operation', when(2023, 1, 10), ol=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        self.make_event('training', when(2024, 3, 10), attended=[self.member], leaders='Ann')
        self.make_event('meeting', when(2024, 3, 10) + timedelta(hours=5), attended=[self.member])   # that evening
        measures, (years, months), options = self.chart_asked_for()
        self.assertEqual([series['label'] for series in years['series']],
                         ['All', 'Operations', 'Trainings', 'Meetings', 'Community'])
        self.assertEqual([p['short'] for p in years['periods']], ["'23", "'24"])
        self.assertEqual(len(months['periods']), 18)
        self.assertEqual([(m['label'], m['title']) for m in measures],
                         [('Days', 'Days attended / unit active days, by type, 2023 to 2024'),
                          ('Events', 'Events attended / unit events, by type, 2023 to 2024'),
                          ('Hours', 'Hours logged, by type, 2023 to 2024')])
        self.assertEqual(options['name'], 'activity')
        # Its question, and the switch's lead as on the unit report.
        self.assertEqual((options['note'], options['measure_switch_label']),
                         ('How often does this member take part, and how does that compare with the unit?', 'Count'))

        def key(label):
            return [name for _, name in self.panel(label)['key']]
        self.assertEqual(key('All'), ['Operations', 'Trainings', 'Meetings', 'Community'])
        self.assertEqual(key('Operations'), ['as OL', 'Other attendance', 'as AHC'])
        self.assertEqual(key('Trainings'), ['as TL or LL', 'Other attendance'])
        self.assertEqual(key('Meetings'), ['Attended'])

        def column(label, period, view=0):
            """For days, events and hours: (the parts that are not nothing, the whole, the figures)."""
            return [([part for part in cell['parts'] if part[1]], cell['total'], cell['tip'])
                    for cell in self.panel(label, view)['cells'][period]]
        # Leading at the foot in the darkest blue; AHC in the lightest.
        self.assertEqual(column('Operations', 0), [
            ([('1-strong', 1)], 1, ['2023', ('1 of 1', 'day'), (1, 'as OL')]),
            ([('1-strong', 1)], 1, ['2023', ('1 of 1', 'event'), (1, 'as OL')]),
            ([('1-strong', 4)], 4, ['2023', ('4.0', 'hours'), ('4.0', 'as OL')])])
        self.assertEqual(column('Operations', 1), [
            ([('1-light', 1)], 1, ['2024', ('1 of 1', 'day'), (1, 'as AHC')]),
            ([('1-light', 1)], 1, ['2024', ('1 of 1', 'event'), (1, 'as AHC')]),
            ([('1-light', 2)], 2, ['2024', ('2.0', 'hours'), ('2.0', 'as AHC')])])
        training = [([('1-strong', 1)], 1, ['2024', ('1 of 1', 'day'), (1, 'as TL or LL')]),
                    ([('1-strong', 1)], 1, ['2024', ('1 of 1', 'event'), (1, 'as TL or LL')]),
                    ([('1-strong', 4)], 4, ['2024', ('4.0', 'hours'), ('4.0', 'as TL or LL')])]
        self.assertEqual(column('Trainings', 1), training)
        # The same in the month it happened, the fifteenth of the months shown.
        self.assertEqual(column('Trainings', 14, view=1),
                         [(parts, whole, ['Mar 2024'] + tip[1:]) for parts, whole, tip in training])
        # A day with a training and a meeting counts once, as a training day;
        # the three events on those two days each count.
        self.assertEqual(column('All', 1), [
            ([('1-strong', 1), ('1', 1)], 2, ['2024', ('2 of 2', 'days')]),
            ([('1-strong', 1), ('1', 1), ('1-light', 1)], 3, ['2024', ('3 of 3', 'events')]),
            ([('1-strong', 2), ('1', 4), ('1-light', 4)], 10, ['2024', ('10.0', 'hours')])])

    def test_table(self):
        self.make_event('operation', when(2023, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        for week in range(7):
            self.make_event('meeting', when(2024, 3, 11) + timedelta(weeks=week), attended=[self.member], hours=160)
        table = member_activity(self.member, NOW)['table']
        self.assertEqual(table['columns'], ['Operations', 'AHC days', 'Trainings', 'Meetings', 'Community', 'Total'])
        # Each cell carries its column's heading, for a screen too narrow for columns.
        self.assertEqual(table['rows'][0]['cells'][0], ('Operations', '1 / 4.0 hours'))
        self.assertEqual([(r['label'], [c for _, c in r['cells'][:2]], r['cells'][-1][1]) for r in table['rows']], [
            ('2023', ['1 / 4.0 hours', ''], '1 / 4.0 hours'),
            ('2024', ['1 / 2.0 hours', 1], '51 / 1,122.0 hours'),
        ])
        self.assertEqual(table['total']['cells'][-1], ('Total', '52 / 1,126.0 hours'))
        # Half hours show, and add up: two years of half an hour each make one hour.
        for year in (2021, 2022):
            self.make_event('community', when(year, 5, 1), attended=[self.member], hours=0.5)
        table = member_activity(self.member, NOW)['table']
        self.assertEqual([dict(r['cells'])['Community'] for r in table['rows'][:2]], ['1 / 0.5 hours', '1 / 0.5 hours'])
        self.assertEqual(dict(table['total']['cells'])['Community'], '2 / 1.0 hours')
        # Duty columns appear only for duties the member has done.
        DoAvailable.objects.create(member=self.other, year=2024, quarter=1, week=3, assigned=True)
        self.make_event('operation', when(2024, 1, 10), ol=[self.other])
        self.assertEqual(member_activity(self.other, NOW)['table']['columns'][:3],
                         ['Operations', 'OL days', 'DO wks'])


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

    def paged(self, event, template):
        """A page for `event`, sent as it started, asking who can go ('Available?') or warning ('Heads Up')."""
        page = Message.objects.create(author=self.other, text='Page', format='page', period=event.period_set.first(),
                                      rsvp_template=RsvpTemplate.objects.get_or_create(name=template)[0])
        Message.objects.filter(id=page.id).update(created_at=event.start_at)

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
        both = [before.id, after.id]
        not_run = operations_not_run(NOW, operations_that_ran(NOW, both), both)
        self.assertEqual(not_run, {before.id: NotRun('called_off', date(2019, 2, 12)),
                                   after.id: NotRun('heads_up', date(2019, 2, 13))})

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
        self.assertEqual(self.years()['2024']['unit_events']['operation'], 0)

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
        self.assertEqual(activity_rows(self.member, NOW)['total']['duty']['ahc'], 1)
        items = self.latest()
        self.assertEqual(items['Operation (as AHC)']['day'], date(2024, 1, 10))
        self.assertEqual(items['Training']['day'], date(2024, 2, 11))


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
        self.assertEqual((total['events']['training'], total['days']['training']), (4, 2))
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
        self.assertEqual(self.not_run(), {warned.id: 'heads_up', early.id: 'called_off'})
        self.assertNotIn(unused, reported_events())
        self.assertIn('Events left out', dict(glossary()))

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
        self.assertEqual((total['hours']['training'], total['hours']['meeting'], total['all_hours']), (4, 1, 5))
        self.assertEqual((total['days']['training'], total['days']['meeting'], total['all_days']), (1, 1, 1))
        # Each row in the lists shows what it logged: what counts, then what is left out, here counted above.
        participants = member_entries(self.member)
        count_entry_days(participants, NOW)
        self.assertEqual([(p.counted_hours, p.left_out_hours) for p in participants], [(4, 0), (1, 2)])
        # Two periods of one operation, 8am to 4pm and noon to 8pm: 12 hours.
        operation = self.make_event('operation', when(2024, 4, 10))
        self.entry(operation, when(2024, 4, 10) - timedelta(hours=5), 8)
        self.entry(operation, when(2024, 4, 10) - timedelta(hours=1), 8, Period.objects.create(event=operation, position=2))
        self.assertEqual(activity_rows(self.member, NOW)['total']['hours']['operation'], 12)

    def test_the_first_to_begin_keeps_the_time_whatever_its_event_s_date(self):
        # The meeting is listed first (its event starts earlier) but its time began later.
        meeting = self.make_event('meeting', when(2024, 3, 9))
        training = self.make_event('training', when(2024, 3, 10))
        self.entry(meeting, when(2024, 3, 10) + timedelta(hours=2), 3)
        self.entry(training, when(2024, 3, 10), 4)
        hours = activity_rows(self.member, NOW)['total']['hours']
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
        self.assertEqual(activity_rows(self.member, NOW)['total']['all_days'], 5)

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
        self.assertEqual((total['days']['training'], total['hours']['training']), (2, 35))


class PagesTestCase(ActivityTestCase):
    def setUp(self):
        super().setUp()
        # The pages read the clock; hold it at NOW so that they do not grow as the tests age.
        self.enterContext(mock.patch('django.utils.timezone.now', return_value=NOW))

    def test_an_entrys_row_and_the_totals_round_its_hours_alike(self):
        # An hour and a quarter is 1.3 hours, half up as written, in the entry's row and in the table.
        self.make_event('training', when(2024, 3, 10), attended=[self.member], hours=1.25)
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>1.3</td>', html=True)
        self.assertContains(response, '1 / 1.3 hours')
        self.assertNotContains(response, '1.2')

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

    def test_pages(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member, self.other])
        client = Client()
        client.force_login(self.other)
        response = client.get(self.member.get_absolute_url())
        self.assertContains(response, 'id="activityTbl"')
        self.assertContains(response, '<td>Operation (in the field)</td>', html=True)
        self.assertContains(response, '<td>10 Jan 2024</td>', html=True)     # dates as on the report
        # One link to the report, in the page's own menu near the top.
        self.assertContains(response, reverse('report_activity_member', args=[self.member.id]), count=1)
        self.make_event('training', when(2024, 2, 1), attended=[self.member], hours=24 * 8)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, 'Days attended / unit active days')
        self.assertContains(response, '<!DOCTYPE html>\n<html lang="en">')
        # The report is sent compressed to a browser that takes it.
        packed = client.get(reverse('report_activity_member', args=[self.member.id]), HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(packed.headers['Content-Encoding'], 'gzip')
        self.assertLess(len(packed.content), len(response.content) / 5)
        self.assertContains(response, '10 Jan 2024')
        # Hours left out are shown in parentheses: all of a mistake, and the
        # part of an entry under way that falls after today, after the part counted.
        self.assertContains(response, '<td>(192.0)</td>', html=True)
        under_way = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=under_way.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 16))
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>35.0 (13.0)</td>', html=True)
        # The glossary at the foot defines the terms, with what holds only on a member's report.
        self.assertContains(response, '<tr><th>Term</th><th>Meaning</th></tr>', html=True)
        # Each table's title is its caption, and each row is named by its first cell.
        self.assertContains(response, '<caption>Days attended / hours logged</caption>', html=True)
        self.assertContains(response, '<caption>Operations</caption>', html=True)
        self.assertContains(response, '<th scope="row">Total</th>', html=True)
        self.assertContains(response, '<th scope="row">Unit active day</th>', html=True)
        self.assertContains(response, 'own days attended count too.')
        self.assertContains(response, 'Hours left out, and time counted on another row, are shown in parentheses.')
        self.assertContains(response, 'counts once, for the one that began first.')
        # Two rows hold only on a member's report: what an AHC day is, and how the All panel counts a day.
        self.assertContains(response, '<th scope="row">AHC days</th>', html=True)
        self.assertContains(response, 'under the first of Operations, Trainings, Meetings and Community.')
        self.assertNotIn('AHC days', dict(glossary()))
        self.assertContains(response, 'no hours are logged for administrative work or DO duty.')
        self.assertNotContains(response, 'Days*')
        unit = dict(glossary())
        self.assertNotIn('On this report', unit['Unit active day'] + unit['Unit event'])
        self.assertNotIn('parentheses', unit['Mistaken times'])
        self.assertTrue(unit['Mistaken times'].startswith('More than {} days'.format(MAX_ENTRY.days)))
        trainee = self.make_member('Dee', 'T')
        response = client.get(trainee.get_absolute_url())
        self.assertNotContains(response, 'id="activityTbl"')
        response = client.get(reverse('report_activity_member', args=[trainee.id]))
        self.assertEqual(response.status_code, 200)

    def test_the_activity_summary_keeps_its_own_styling(self):
        # The new reports' chart frame and glossary rules are theirs; the summary has only its tables'.
        client = Client()
        client.force_login(self.other)
        summary = client.get('/reports/activity-summary/?start=2024-01-01&end=2024-12-31')
        self.assertContains(summary, 'tr.member:nth-child(even)')
        self.assertNotContains(summary, '.chart')
        self.assertNotContains(summary, 'glossary')
        report = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(report, '.chart-head { background-color: #ccc;')

    def test_report_with_an_unknown_type_of_event(self):
        event = self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        Event.objects.filter(pk=event.pk).update(type='other')
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        # It is not counted, so there is nothing to show, not a year of zeros.
        self.assertIsNone(activity_rows(self.member, NOW))
        self.assertNotContains(response, 'class="chart"')


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
                got = rows and {r['year']: (r['days'], r['active_days'], r['events'], r['unit_events'],
                                            {t: round(r['hours'][t], 6) for t in TYPES}, r['all_days'])
                                for r in rows['years']}
                self.assertEqual(got, self.expected(now, days_of), 'seed {}, now {}'.format(seed, now))
