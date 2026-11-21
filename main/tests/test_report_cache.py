"""The activity reports' cache (report_cache): a value is used again only while the data it was built from, the
team's rules and the time it was built for still hold, in every server worker."""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.db import models
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from main.lib import counting, report_cache
from main.lib import unit_activity as unit_report
from main.lib.activity import member_activity
from main.lib.counting import member_entries
from main.models import (Cert, CertSubType, CertType, DoAvailable, Distribution, Event, Member, Message, Participant,
                         Period, RsvpTemplate, Unavailable)
from main.tests.helpers import ActivityTestCase, when


class ReportCacheTestCase(ActivityTestCase):
    """The data is written with the clock running, as on the site, so that each write moves updated_at. The cache
    is asked at one moment throughout (self.now), so that only a change in what a value was built from rebuilds
    it, not the clock passing into another span of the expiry: noon today by the local clock, so that an hour
    logged from then, or from the next span, stays within its local day whenever the tests run."""

    def setUp(self):
        super().setUp()
        self.now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        self.third = self.make_member('Cat', 'T')
        self.callout = RsvpTemplate.objects.create(name='Available?')
        self.operation = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.training = self.make_event('training', when(2024, 3, 7), attended=[self.member, self.other])
        self.page = Message.objects.create(author=self.member, text='Callout', format='page',
                                           rsvp_template=self.callout, period=self.operation.period_set.first())
        Message.objects.filter(id=self.page.id).update(created_at=when(2024, 2, 7) - timedelta(hours=1))
        self.endorse(self.other, 'T', date(2010, 1, 1))                 # joined before anything here
        self.reply = Distribution.objects.create(message=self.page, member=self.other, rsvp=True, rsvp_answer=True,
                                                 response_seconds=60)
        self.busy = Unavailable.objects.create(member=self.member, start_on=date(2024, 5, 1), end_on=date(2024, 5, 3))
        self.week = DoAvailable.objects.create(member=self.member, year=2024, quarter=1, week=2, assigned=True)

    def builds(self, function):
        """Counts the calls to one of the builders the cache stands in front of."""
        return mock.patch.object(*function, wraps=getattr(*function))

    def at(self, moment):
        """The cache's clock held at `moment`, while the data is still written with the clock running."""
        return mock.patch.object(report_cache, 'timezone', SimpleNamespace(now=lambda: moment,
                                                                           localtime=timezone.localtime))

    def unit_report(self):
        """The unit report's figures as the page reads them, at self.now."""
        with self.at(self.now):
            return report_cache.unit_activity()

    def first_day(self):
        return report_cache.records_from(self.now)

    def unit_days(self):
        """What the unit did as a member's report reads it (report_cache.member_report), at self.now."""
        return report_cache.member_report(self.now)[1]()

    def unit_days_fresh(self):
        since = counting.records_from(self.now)
        return since and counting.unit_since(since, self.now, since)

    def edit(self, row, **values):
        for field, value in values.items():
            setattr(row, field, value)
        row.save()

    # A second load with nothing changed asks the database only for the fingerprint, and gives what a build
    # would.

    def test_a_second_load_with_nothing_changed_builds_nothing(self):
        self.unit_report()
        with self.builds((unit_report, 'unit_activity')) as built, self.assertNumQueries(1):
            warm = self.unit_report()
        self.assertEqual(built.call_count, 0)
        self.assertEqual(warm, unit_report.unit_activity(self.now))
        self.unit_days()
        with self.builds((counting, 'records_from')) as first, self.builds((counting, 'unit_since')) as unit:
            with self.assertNumQueries(1):                 # the tables both read, asked once
                since, unit_days = report_cache.member_report(self.now)
                kept = unit_days()
        self.assertEqual((first.call_count, unit.call_count), (0, 0))
        self.assertEqual((since, kept), (counting.records_from(self.now), self.unit_days_fresh()))

    # Every write to a table a value reads is seen on its next load: an edit moves its latest updated_at, an
    # addition that too, and a deletion its count of rows. A deletion that leaves a table as it was before an
    # earlier write leaves its fingerprint as it was then too, and the value then kept, which is that of the same
    # rows, may be served again: each write sets updated_at to the time it is made, so the same count and the
    # same latest time mean the same rows.

    def assert_rebuilt(self, write, changes_figures=True):
        before = self.unit_report()
        write()
        after = self.unit_report()
        self.assertEqual(after, unit_report.unit_activity(self.now))
        if changes_figures:
            self.assertNotEqual(after, before)

    def test_writes_to_events(self):
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(self.training, title='Test'))      # a test event counts nowhere
        with self.subTest('add'):
            self.assert_rebuilt(lambda: self.make_event('meeting', when(2024, 4, 7), attended=[self.member]))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: self.operation.delete())

    def test_writes_to_periods(self):
        second = Period.objects.create(event=self.training, position=2)
        Participant.objects.create(period=second, member=self.third, en_route_at=when(2024, 3, 8),
                                   return_home_at=when(2024, 3, 8) + timedelta(hours=4))
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(second, event=self.operation))      # the third now on the operation
        with self.subTest('add'):
            self.assert_rebuilt(lambda: Period.objects.create(event=self.training, position=3), changes_figures=False)
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: second.delete())

    def test_writes_to_entries(self):
        entry = Participant.objects.get(period__event=self.training, member=self.other)
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(entry, return_home_at=entry.en_route_at + timedelta(hours=9)))
        with self.subTest('add'):
            self.assert_rebuilt(lambda: Participant.objects.create(
                period=self.training.period_set.first(), member=self.third, en_route_at=when(2024, 3, 7),
                return_home_at=when(2024, 3, 7) + timedelta(hours=3)))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: entry.delete())

    def test_writes_to_members(self):
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(self.other, status='G'))           # a guest counts on no unit figure
        with self.subTest('add'):
            self.assert_rebuilt(lambda: self.make_member('Dee', 'FM'), changes_figures=False)
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: self.third.delete(), changes_figures=False)
            self.assert_rebuilt(lambda: self.member.delete())

    def test_writes_to_pages(self):
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(self.page, rsvp_template=None))    # no longer a callout page
        with self.subTest('add'):
            def add():
                page = Message.objects.create(author=self.member, text='Callout', format='page', period=self.operation
                                              .period_set.first(), rsvp_template=self.callout)
                Distribution.objects.create(message=page, member=self.member, rsvp=False)
            self.assert_rebuilt(add)
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: Message.objects.filter(author=self.member).delete())

    def test_writes_to_replies(self):
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(self.reply, response_seconds=3 * 3600))
        with self.subTest('add'):
            self.assert_rebuilt(lambda: Distribution.objects.create(message=self.page, member=self.member, rsvp=False))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: self.reply.delete())

    def test_writes_to_reply_templates(self):
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(self.callout, name='Who can go'))  # no longer the callout template
        with self.subTest('add'):
            self.assert_rebuilt(lambda: RsvpTemplate.objects.create(name='Available?'), changes_figures=False)
        with self.subTest('delete'):
            # Deleting one empties its pages' template by an update of their own, which moves no updated_at on
            # them: the template's count of rows moves instead.
            spare = RsvpTemplate.objects.get(name='Available?')
            self.edit(self.page, rsvp_template=spare)
            self.assert_rebuilt(lambda: spare.delete())

    def test_writes_to_busy_periods(self):
        Distribution.objects.create(message=self.page, member=self.member, rsvp=False)
        busy_then = date(2024, 2, 6)
        with self.subTest('add'):
            self.assert_rebuilt(lambda: Unavailable.objects.create(member=self.member, start_on=busy_then,
                                                                   end_on=busy_then + timedelta(days=2)))
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(Unavailable.objects.get(start_on=busy_then), member=self.third))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: Unavailable.objects.filter(start_on=busy_then).delete(), changes_figures=False)

    def test_writes_to_endorsements(self):
        # A promotion's endorsement draws the chart of promotions; moving or deleting it redraws it.
        kind = CertSubType.objects.create(type=CertType.objects.get(name='Endorsements'), name='FM')
        with self.subTest('add'):
            self.assert_rebuilt(lambda: Cert.objects.create(member=self.member, subtype=kind, earned_on=date(2024, 2, 1)))
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(Cert.objects.get(subtype=kind), earned_on=None, comment='2025'))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: Cert.objects.filter(subtype=kind).delete())
        # Endorsements are read by the names of their kind and its type.
        Cert.objects.create(member=self.member, subtype=kind, earned_on=date(2024, 2, 1))
        with self.subTest('rename its kind'):
            self.assert_rebuilt(lambda: self.edit(kind, name='TM'))
        with self.subTest('rename its type'):
            self.assert_rebuilt(lambda: self.edit(kind.type, name='Certificates'))

    def test_writes_to_do_weeks(self):
        # A DO week years before the rest moves the records' first year, and with it every chart's.
        with self.subTest('add'):
            self.assert_rebuilt(lambda: DoAvailable.objects.create(member=self.member, year=2023, quarter=1, week=2,
                                                                   assigned=True))
        with self.subTest('edit'):
            self.assert_rebuilt(lambda: self.edit(DoAvailable.objects.get(year=2023), year=2022))
        with self.subTest('delete'):
            self.assert_rebuilt(lambda: DoAvailable.objects.filter(year=2022).delete())

    # The first day both reports count from, likewise, for every table it reads.

    def assert_first_day_rebuilt(self, write, changes=True):
        before = self.first_day()
        write()
        after = self.first_day()
        self.assertEqual(after, counting.records_from(self.now))
        if changes:
            self.assertNotEqual(after, before)

    def test_writes_to_events_move_the_first_day(self):
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(self.training, start_at=when(2022, 3, 7)))
        with self.subTest('add'):
            self.assert_first_day_rebuilt(lambda: self.make_event('meeting', when(2020, 4, 7), attended=[self.third]))
        with self.subTest('delete'):
            self.assert_first_day_rebuilt(lambda: Event.objects.filter(start_at__year=2020).delete())

    def test_writes_to_periods_move_the_first_day(self):
        empty = self.make_event('training', when(2021, 3, 7))
        moved = self.training.period_set.first()
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(moved, event=empty))       # its time on an event of 2021
        with self.subTest('add'):
            self.assert_first_day_rebuilt(lambda: Period.objects.create(event=empty, position=2), changes=False)
        with self.subTest('delete'):
            self.assert_first_day_rebuilt(lambda: moved.delete())

    def test_writes_to_entries_move_the_first_day(self):
        empty = self.make_event('training', when(2021, 3, 7))
        with self.subTest('add'):
            self.assert_first_day_rebuilt(lambda: Participant.objects.create(
                period=empty.period_set.first(), member=self.other, en_route_at=when(2021, 3, 7),
                return_home_at=when(2021, 3, 7) + timedelta(hours=4)))
        entry = Participant.objects.get(period__event=empty)
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(entry, en_route_at=None, return_home_at=None))
        with self.subTest('delete'):
            self.assert_first_day_rebuilt(lambda: entry.delete(), changes=False)

    def test_writes_to_members_move_the_first_day(self):
        self.make_event('training', when(2021, 3, 7), attended=[self.third])
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(self.third, status='G'))   # a guest's time counts nowhere
        with self.subTest('add'):
            self.assert_first_day_rebuilt(lambda: self.make_member('Dee', 'FM'), changes=False)
        with self.subTest('delete'):
            self.edit(self.third, status='T')
            self.assert_first_day_rebuilt(lambda: self.third.delete())

    def test_writes_to_pages_move_the_first_day(self):
        # An operation of 2023 with nobody listed counts as called off, the records starting then, until pages
        # are recorded from before it: then, with no page of its own, it was never used and counts nowhere.
        unused = self.make_event('operation', when(2023, 6, 7))

        def add():
            page = Message.objects.create(author=self.member, text='Callout', format='page',
                                          period=self.operation.period_set.first())
            Message.objects.filter(id=page.id).update(created_at=when(2023, 1, 7))
        with self.subTest('add'):
            self.assert_first_day_rebuilt(add)
        early = Message.objects.get(created_at=when(2023, 1, 7))
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(early, period=unused.period_set.first()))
        with self.subTest('delete'):
            self.assert_first_day_rebuilt(lambda: early.delete(), changes=False)

    def test_writes_to_do_weeks_move_the_first_day(self):
        with self.subTest('add'):
            self.assert_first_day_rebuilt(lambda: DoAvailable.objects.create(member=self.member, year=2022, quarter=1,
                                                                             week=2, assigned=True))
        with self.subTest('edit'):
            self.assert_first_day_rebuilt(lambda: self.edit(DoAvailable.objects.get(year=2022), year=2021))
        with self.subTest('delete'):
            self.assert_first_day_rebuilt(lambda: DoAvailable.objects.filter(year=2021).delete())

    # What the unit did, for the member reports, likewise, for every table it reads.

    def assert_unit_days_rebuilt(self, write, changes=True):
        before = self.unit_days()
        write()
        after = self.unit_days()
        self.assertEqual(after, self.unit_days_fresh())
        if changes:
            self.assertNotEqual(after, before)

    def test_writes_the_units_days_read(self):
        self.endorse(self.third, 'T', date(2024, 1, 1))
        second = Period.objects.create(event=self.training, position=2)
        with self.subTest('event'):
            self.assert_unit_days_rebuilt(lambda: self.edit(self.training, title='Test'))
            self.assert_unit_days_rebuilt(lambda: self.make_event('meeting', when(2024, 4, 7), attended=[self.member]))
            self.assert_unit_days_rebuilt(lambda: Event.objects.filter(start_at__month=4).delete())
        self.edit(self.training, title='Training')
        with self.subTest('period'):
            Participant.objects.create(period=second, member=self.third, en_route_at=when(2024, 3, 9),
                                       return_home_at=when(2024, 3, 9) + timedelta(hours=4))
            meeting = self.make_event('meeting', when(2024, 5, 9))
            self.assert_unit_days_rebuilt(lambda: self.edit(second, event=meeting))         # a meeting's day now
            self.assert_unit_days_rebuilt(lambda: Period.objects.create(event=meeting, position=2), changes=False)
            self.assert_unit_days_rebuilt(lambda: second.delete())
        with self.subTest('entry'):
            entry = Participant.objects.get(period__event=self.training, member=self.other)
            self.assert_unit_days_rebuilt(lambda: self.edit(entry, en_route_at=when(2024, 3, 10),
                                                            return_home_at=when(2024, 3, 10) + timedelta(hours=4)))
            self.assert_unit_days_rebuilt(lambda: Participant.objects.create(
                period=self.training.period_set.first(), member=self.third, en_route_at=when(2024, 3, 11),
                return_home_at=when(2024, 3, 11) + timedelta(hours=4)))
            self.assert_unit_days_rebuilt(lambda: entry.delete())
        with self.subTest('endorsement'):
            # The joining endorsement dates a member's joining, and their day at a training before it is a guest's;
            # without it, they joined on that day, their first at a training.
            joined = Cert.objects.get(member=self.third)
            self.assert_unit_days_rebuilt(lambda: self.edit(joined, earned_on=date(2024, 3, 12)))
            self.assert_unit_days_rebuilt(lambda: self.edit(joined.subtype, name='FM'))
            self.edit(joined.subtype, name='T')
            self.assert_unit_days_rebuilt(lambda: self.edit(joined.subtype.type, name='Certificates'))
            self.edit(joined.subtype.type, name='Endorsements')
            self.assert_unit_days_rebuilt(lambda: joined.delete())
        with self.subTest('member'):
            self.assert_unit_days_rebuilt(lambda: self.edit(self.third, status='G'))
            self.assert_unit_days_rebuilt(lambda: self.make_member('Dee', 'FM'), changes=False)
            self.edit(self.third, status='T')
            self.assert_unit_days_rebuilt(lambda: self.third.delete())

    def test_a_page_rebuilds_the_first_day_alone_and_a_reply_or_a_busy_period_neither(self):
        # Pages and replies are the busiest writes during a callout. A page may move the first day (an operation
        # with nobody listed and no page, from when pages were first recorded, counts nowhere), so it is built
        # again; what the unit did is not, as a page cannot change it. A reply, or a busy period, rebuilds neither.
        report_cache.member_report(self.now)[1]()
        Message.objects.create(author=self.member, text='Callout', format='page', period=self.operation.period_set
                               .first(), rsvp_template=self.callout)
        with self.builds((counting, 'records_from')) as first, self.builds((counting, 'unit_since')) as unit:
            report_cache.member_report(self.now)[1]()
        self.assertEqual((first.call_count, unit.call_count), (1, 0))
        self.edit(self.reply, response_seconds=900)
        Unavailable.objects.create(member=self.other, start_on=date(2024, 6, 1), end_on=date(2024, 6, 2))
        with self.builds((counting, 'records_from')) as first, self.builds((counting, 'unit_since')) as unit:
            report_cache.member_report(self.now)[1]()
            report_cache.records_from(self.now)
        self.assertEqual((first.call_count, unit.call_count), (0, 0))

    # The first day a member's report counts from is part of what the unit's days were read for: a DO week
    # that makes years of time no longer a stray record moves it, and the unit's days with it.

    def test_a_first_day_moved_by_a_do_week_gives_the_units_days_from_it(self):
        self.make_event('training', when(2015, 3, 7), attended=[self.other])       # a stray, years before the rest
        before = self.unit_days()
        for year in (2018, 2021):
            DoAvailable.objects.create(member=self.member, year=year, quarter=1, week=2, assigned=True)
        after = self.unit_days()
        self.assertEqual(report_cache.records_from(self.now), date(2015, 1, 1))
        self.assertEqual(after, self.unit_days_fresh())
        self.assertNotEqual(after, before)

    # The team's rules in force, the time zone and the time are part of what a value was built from.

    def test_a_change_of_the_teams_rules_is_not_served_the_old_values(self):
        self.make_event('training', when(2015, 3, 7), attended=[self.other])       # a stray at STRAY_BEFORE 3
        self.make_event('training', when(2024, 6, 7), attended=[self.member], hours=40)
        report, first, unit = self.unit_report(), self.first_day(), self.unit_days()
        with override_settings(ACTIVITY_REPORTS={'LONG_DAY': 2, 'STRAY_BEFORE': 10, 'MAX_ENTRY_DAYS': 1}):
            self.assertEqual(self.unit_report(), unit_report.unit_activity(self.now))
            self.assertEqual(self.first_day(), counting.records_from(self.now))
            self.assertEqual(self.unit_days(), self.unit_days_fresh())
            self.assertNotEqual((self.unit_report(), self.first_day(), self.unit_days()), (report, first, unit))
            self.assertNotEqual(self.first_day(), first)
            self.assertNotEqual(self.unit_days(), unit)

    def test_another_zone_or_another_day_is_not_served_the_other_values(self):
        # With the span of the expiry held still, the zone and the date alone tell the values apart.
        with mock.patch.object(report_cache, 'EXPIRY', 10 ** 12):
            # Noon in UTC is Sunday 10 March in California, already Monday 11 March on Kiritimati.
            self.make_event('training', when(2024, 3, 10) - timedelta(hours=8), attended=[self.member])
            values = (self.unit_report(), self.unit_days())
            with override_settings(TIME_ZONE='Pacific/Kiritimati'):
                self.assertEqual((self.unit_report(), self.unit_days()),
                                 (unit_report.unit_activity(self.now), self.unit_days_fresh()))
                self.assertNotEqual((self.unit_report(), self.unit_days()), values)
            # Time logged for tomorrow counts tomorrow, not today.
            tomorrow = self.now + timedelta(days=1)
            self.make_event('training', tomorrow, attended=[self.member], hours=1)
            today = (self.unit_report(), self.unit_days())
            with self.at(tomorrow):
                self.assertEqual(report_cache.unit_activity(), unit_report.unit_activity(tomorrow))
            since = counting.records_from(tomorrow)
            self.assertEqual(report_cache.records_from(tomorrow), since)
            self.assertEqual(report_cache.member_report(tomorrow)[1](), counting.unit_since(since, tomorrow, since))
            self.assertNotEqual(report_cache.member_report(tomorrow)[1](), today[1])

    def test_another_zone_on_the_same_date_is_not_served_the_other_values(self):
        # 23:00 on 6 March in California is already 7 March in Denver; at 18:00 UTC the two share the date.
        start = datetime(2024, 3, 7, 7, 0, tzinfo=dt_timezone.utc)
        self.make_event('training', start, attended=[self.member], hours=0.75)
        moment = self.now.replace(hour=18, minute=0, second=0, microsecond=0)
        with self.at(moment):
            before = (report_cache.unit_activity(), report_cache.member_report(moment)[1]())
        with override_settings(TIME_ZONE='America/Denver'):
            self.assertEqual(timezone.localtime(moment).date(), moment.date())
            since = counting.records_from(moment)
            with self.at(moment):
                after = (report_cache.unit_activity(), report_cache.member_report(moment)[1]())
            self.assertEqual(after, (unit_report.unit_activity(moment), counting.unit_since(since, moment, since)))
        self.assertEqual(timezone.localtime(moment).date(), moment.date())
        self.assertNotEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])

    def test_a_rule_that_moves_only_the_units_days_is_not_served_the_old_ones(self):
        self.make_event('training', when(2024, 6, 7), attended=[self.member], hours=40)
        first, unit = self.first_day(), self.unit_days()
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 1}):          # 40 hours is now too long
            self.assertEqual(self.first_day(), first)
            self.assertEqual(self.unit_days(), self.unit_days_fresh())
            self.assertNotEqual(self.unit_days(), unit)

    def test_time_passing_is_seen_within_the_expiry(self):
        # An operation under way, saved to finish at 20:30; its member only listed, so it is called off once it has.
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=30, hours=18)
        self.make_event('operation', start, no_time=[self.third], hours=2.5)
        expiry = timedelta(seconds=report_cache.EXPIRY)
        at = start + timedelta(hours=2, minutes=29)
        with self.at(at):
            before = report_cache.unit_activity()
        with self.at(at + expiry), self.builds((unit_report, 'unit_activity')) as built:
            after = report_cache.unit_activity()
        self.assertEqual(built.call_count, 1)
        self.assertEqual(after, unit_report.unit_activity(at + expiry))
        self.assertNotEqual(after, before)
        with self.at(at + timedelta(days=1)):
            self.assertEqual(report_cache.unit_activity(), unit_report.unit_activity(at + timedelta(days=1)))

    def test_the_member_sides_values_are_built_again_in_a_later_span_of_the_expiry(self):
        # With no time but an event of the next span, the records begin then.
        Event.objects.all().delete()
        DoAvailable.objects.all().delete()
        later = self.now + timedelta(seconds=report_cache.EXPIRY)
        self.make_event('training', later - timedelta(seconds=1), attended=[self.member], hours=1)
        self.assertEqual(report_cache.records_from(self.now), None)
        self.assertEqual(report_cache.records_from(later), counting.records_from(later))
        self.assertNotEqual(counting.records_from(later), None)
        self.assertEqual(report_cache.member_report(later)[1](),
                         counting.unit_since(counting.records_from(later), later, counting.records_from(later)))

    # Two server workers each keep their own cache: each asks the database, so both see an edit at once.

    def test_two_workers_agree_after_an_edit_made_through_one(self):
        one, two = LocMemCache('worker-one', {}), LocMemCache('worker-two', {})
        with mock.patch.object(report_cache, 'cache', one):
            self.unit_report()
        with mock.patch.object(report_cache, 'cache', two):
            self.unit_report()
        self.edit(Participant.objects.get(period__event=self.training, member=self.other),
                  return_home_at=when(2024, 3, 7) + timedelta(hours=10))
        with mock.patch.object(report_cache, 'cache', one):
            seen_by_one = self.unit_report()
        with mock.patch.object(report_cache, 'cache', two):
            seen_by_two = self.unit_report()
        self.assertEqual(seen_by_one, seen_by_two)
        self.assertEqual(seen_by_one, unit_report.unit_activity(self.now))

    # Each value has one entry in a worker's cache, replaced when it is built again: many spans of the expiry
    # and many edits leave three.

    def test_many_spans_and_edits_leave_one_entry_for_each_value(self):
        worker = LocMemCache('worker', {})
        entry = Participant.objects.get(period__event=self.training, member=self.other)
        with mock.patch.object(report_cache, 'cache', worker):
            for span in range(12):
                moment = self.now + span * timedelta(seconds=report_cache.EXPIRY)
                with self.at(moment):
                    report_cache.unit_activity()
                report_cache.member_report(moment)[1]()
                self.edit(entry, return_home_at=when(2024, 3, 7) + timedelta(hours=1 + span % 5))
        self.assertLessEqual(len(worker._cache), 3)

    # What is kept is plain data, built in full: nothing that queries later, and nothing shared with a caller.

    def test_what_is_kept_holds_no_query_and_no_row(self):
        kept = [self.unit_report(), self.first_day(), self.unit_days()]

        def walk(value):
            self.assertNotIsInstance(value, (models.QuerySet, models.Model))
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(key)
                    walk(item)
            elif isinstance(value, (list, tuple, set, frozenset)):
                for item in value:
                    walk(item)
        walk(kept)
        kept[0]['charts'].clear()
        self.assertTrue(self.unit_report()['charts'])

    # The member report's unit columns read the unit's days from the records' first day, kept once for every
    # member: the same figures as reading them from each member's own first day; and a member with nothing to
    # count does not ask for them.

    def test_every_member_report_reads_the_kept_unit_days_as_its_own(self):
        self.make_event('community', when(2024, 9, 7), attended=[self.third])
        since, unit_days = report_cache.member_report(self.now)
        for member in Member.objects.all():
            entries = member_entries(member)
            self.assertEqual(counting.activity_rows(member, self.now, entries, since, unit=unit_days),
                             counting.activity_rows(member, self.now, entries, since), member)
            self.assertEqual(member_activity(member, self.now, entries, since, unit=unit_days),
                             member_activity(member, self.now, entries, since), member)

    def test_a_member_with_nothing_to_count_never_asks_for_the_units_days(self):
        idle = self.make_member('Eve', 'FM')
        since = counting.records_from(self.now)

        def never():
            self.fail('the unit was read for a member with nothing to count')
        self.assertIsNone(counting.activity_rows(idle, self.now, member_entries(idle), since, unit=never))

    def test_a_function_giving_nothing_reads_the_units_days_itself(self):
        since = counting.records_from(self.now)
        entries = member_entries(self.member)
        self.assertEqual(counting.activity_rows(self.member, self.now, entries, since, unit=lambda: None),
                         counting.activity_rows(self.member, self.now, entries, since))

    # As the pages read them: a member's report's unit columns move when another member logs time, and the
    # member page's Last table when the first day moves.

    def test_the_pages_show_another_members_time_on_their_next_load(self):
        client = Client()
        client.force_login(self.member)
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            report = client.get(reverse('report_activity_member', args=[self.member.id])).context['activity']
            self.make_event('training', when(2024, 3, 21), attended=[self.other])
            again = client.get(reverse('report_activity_member', args=[self.member.id])).context['activity']
        self.assertNotEqual(again, report)
        self.assertEqual(again, member_activity(self.member, self.now, member_entries(self.member),
                                                counting.records_from(self.now)))
        # A community event of 2015 is a stray, years before the rest, so the member page has no Community line,
        # until time logged by another member in the years between ends it being one.
        self.make_event('community', when(2015, 6, 6), attended=[self.member])
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            page = client.get(reverse('member_detail', args=[self.member.id]))
            for year in (2018, 2021):
                self.make_event('training', when(year, 3, 7), attended=[self.other])
            again = client.get(reverse('member_detail', args=[self.member.id]))
        self.assertContains(page, '<tr><td>Community</td><td>None</td><td></td><td></td></tr>', html=True)
        self.assertContains(again, '<td>06 Jun 2015</td>', html=True)

    # A write that does not go through a model's save is not seen until the expiry passes. This is a tripwire for
    # the common ways of making one, in the site's code and its migrations, so that the next person finds out
    # (docs/activity-reports.md); not a proof: a queryset's update or bulk_update, a save of chosen fields, SQL
    # through a cursor or a migration's RunSQL, loaddata and a raw save. The lines it lets pass are the updates of
    # sets and dicts, the Google APIs' updates, the cache's own read, and the member page's time limit for its Last
    # table, as they are today.
    KNOWN = {
        ('main/lib/admin.py', 'return self.directory.users().update('),
        ('main/lib/gcal.py', 'event = self.client.events().update('),
        ('main/lib/charts.py', "cell.update(_sizes([c[m]['total'] for m in numbers], scales, above=True))"),
        ('main/lib/counting.py', 'days[event_type].update(hours)'),
        ('main/lib/counting.py',
         'counted.update(zip(indexes, entries_hours([entries[i][1:6] for i in indexes], now, tz, since)))'),
        ('main/lib/report_cache.py', 'cursor.execute(sql)'),
        ('main/lib/unit_counting.py', 'reportable_days[entry.member].update(entry.hours)'),
        ('main/lib/unit_counting.py', 'attended_days[t].update((entry.member, day) for day in entry.hours)'),
        ('main/lib/unit_counting.py', "counted['unit']['days'][t].update(map(_year_and_part, active_days[t]))"),
        ('main/lib/unit_counting.py',
         "counted['people']['days'][t].update(_year_and_part(day) for _, day in attended_days[t])"),
        ('main/lib/unit_counting.py', "counted['unit']['events'][t].update(map(_year_and_part, held[t].values()))"),
        ('main/lib/unit_counting.py',
         "counted['people']['events'][t].update(map(_year_and_part, attended[t].values()))"),
        ('main/views/api_views.py', 'context.update({'),
        ('main/views/member_views.py', 'context.update(self.get_forms(member))'),
        ('main/views/member_views.py',
         'context[\'cursor\'].cursor.execute("SELECT set_config(\'statement_timeout\', %s, true)", [milliseconds])'),
    }

    def test_no_code_of_the_site_writes_past_save(self):
        root = Path(__file__).resolve().parents[2]
        writes = re.compile(r'\.a?update\(|\ba?bulk_update\(|\bupdate_fields\b|cursor(\(\))?\.execute\(|RunSQL\(|'
                            r'loaddata|save_base\(\s*raw')
        found = sorted({(str(path.relative_to(root)), line.strip())
                        for package in ('main', 'bamru_net') for path in (root / package).rglob('*.py')
                        if 'tests' not in path.relative_to(root).parts
                        for line in path.read_text().splitlines() if writes.search(line)} - self.KNOWN)
        self.assertEqual(found, [])
