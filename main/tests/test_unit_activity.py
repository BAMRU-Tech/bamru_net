import re
import time
from unittest import mock
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from main.lib.counting import TYPES, first_year, operations_that_ran
from main.lib.report_settings import report_settings
from main.lib.unit_activity import early_band, unit_activity
from main.lib.unit_counting import unit_entries, unit_rows
from main.models import Distribution, Event, Member, Message, Participant, Period, RsvpTemplate
from main.tests.helpers import NOW, ActivityTestCase, every_operation, when


class UnitActivityTestCase(ActivityTestCase):
    def setUp(self):
        super().setUp()
        self.third = self.make_member('Cat', 'T')

    def make_member(self, name, status):
        """A member whose status was recorded in 1990, before any event in these tests, rather than on
        the real date the test runs, which falls after the tests' own today."""
        member = super().make_member(name, status)
        Member.history.filter(id=member.id).update(history_date=when(1990, 1, 1))
        return member

    def years(self):
        return unit_rows(NOW)['years']

    def chart(self, name):
        return next(c for c in unit_activity(NOW)['charts'] if c['name'] == name)

    def panel(self, name, label, view=0, option=None):
        """A chart's panel; for a chart with a menu, that of the option with this label."""
        chart = self.chart(name)
        if option:
            chart = next(o['chart'] for o in chart['menu']['options'] if o['label'] == option)
        return next(p for p in chart['views'][view]['panels'] if p['label'] == label)

    def column_tips(self, name, label, measure=None, view=0, option=None):
        """Each column's hover text, as the chart gives it, for the measure of that label, or the one the
        chart starts on."""
        # A column's figures are in the order the measures are drawn, the one started on first.
        number = next(m['number'] for m in self.chart(name)['measures'] if m['label'] == measure) if measure else 1
        return [c['tips'][number - 1] for c in self.panel(name, label, view, option)['cells']]

    def tips(self, name, label, measure=None, view=0, option=None):
        """Each column's hover text as it reads: its heading, then each line's number and label, joined
        with " | "; for the tests of a chart's wording."""
        return [' | '.join([tip['head']] + [line['text'] if 'text' in line else '{} {}'.format(line['number'],
                                                                                            line['label'])
                                            for line in tip['lines']])
                for tip in self.column_tips(name, label, measure, view, option)]

    def figures(self, name, label, measure=None, view=0, option=None):
        """Each column's figures, the number on each line of its hover text, for what a chart adds up
        itself: a year picked from its menu, or the bands of a column."""
        return [[line['number'] for line in tip['lines'] if 'number' in line]
                for tip in self.column_tips(name, label, measure, view, option)]

    def drawn(self, name, label, view=0, option=None):
        """Whether each of a chart's columns has anything in it."""
        return [cell['drawn'] for cell in self.panel(name, label, view, option)['cells']]

    def served_page(self):
        """The report's page as a member signed in is served it, on the tests' today."""
        self.member.set_password('password')
        self.member.save()
        client = Client()
        client.login(username=self.member.username, password='password')
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            return client.get(reverse('report_activity_unit')).content.decode()

    def test_each_entry_as_the_report_counts_it(self):
        self.make_event('operation', when(2024, 2, 7), ol=[self.member], ahc=[self.other])
        self.make_event('training', when(2024, 2, 8), ahc=[self.other], leaders='Bob')       # AHC means nothing here
        event = self.make_event('training', when(2024, 2, 9), attended=[self.third])
        Event.objects.filter(id=event.id).update(title='Map and compass *G')
        self.make_event('operation', when(2024, 3, 1), attended=[self.third], hours=24 * 8)  # too long to be right
        self.make_event('meeting', when(2024, 6, 14), attended=[self.member], hours=48)     # runs past today
        got = sorted(unit_entries(NOW), key=lambda e: (e.started, e.member))
        self.assertEqual([(e.type, e.member, e.in_field, e.led, e.ol, e.members_only, e.responder) for e in got],
                         [('operation', self.member.id, True, False, True, True, True),
                          ('operation', self.other.id, False, False, False, True, False),
                          ('training', self.other.id, True, True, False, True, False),
                          ('training', self.third.id, True, False, False, False, False),
                          ('operation', self.third.id, True, False, False, True, True),
                          ('meeting', self.member.id, True, False, False, False, False)])
        too_long, today = got[4], got[5]
        self.assertEqual((too_long.span, too_long.hours), (None, {too_long.started: 0}))
        self.assertEqual(list(today.hours), [date(2024, 6, 14), date(2024, 6, 15)])     # the 16th is left for later

    def test_nothing_logged(self):
        self.assertEqual(unit_activity(NOW)['charts'], [])

    def test_the_units_days_and_hours_count_once_and_peoples_once_each(self):
        self.make_event('training', when(2023, 3, 4), attended=[self.member, self.other])     # a Saturday
        self.make_event('training', when(2023, 3, 4), attended=[self.member], hours=6)        # overlapping it
        self.make_event('training', when(2023, 5, 9), attended=[self.other], hours=6)         # a Tuesday
        self.make_event('meeting', when(2024, 1, 9), attended=[self.member])
        years = self.years()
        self.assertEqual(years[2023].participation['unit']['days']['training'], {'weekday': 1, 'weekend': 1})
        self.assertEqual(years[2023].participation['people']['days']['training'], {'weekday': 1, 'weekend': 2})
        self.assertEqual(years[2023].participation['unit']['hours']['training'], {'weekday': 6, 'weekend': 6})
        # Ann logged the same four hours on both trainings; they count once: her 6 and Bob's 4.
        self.assertEqual(years[2023].participation['people']['hours']['training'], {'weekday': 6, 'weekend': 10})
        self.assertEqual(years[2023].participation['unit']['days']['operation'], {'weekday': 0, 'weekend': 0})
        self.assertEqual(years[2024].participation['unit']['days']['meeting'], {'weekday': 1, 'weekend': 0})
        # Events count each one: two unit events on the Saturday, three events attended.
        self.assertEqual(years[2023].participation['unit']['events']['training'], {'weekday': 1, 'weekend': 2})
        self.assertEqual(years[2023].participation['people']['events']['training'], {'weekday': 1, 'weekend': 3})

    def test_the_units_hours_stay_on_the_days_they_fell_on_and_members_go_with_their_days(self):
        # 11pm on a Friday to 9am on the Saturday: the Friday hour is too short to be a day, so the member's
        # hour goes with the Saturday, a weekend day; the unit was out that hour on the Friday, a weekday.
        start = self.local(2024, 2, 9, 23)
        self.make_event('operation', start, attended=[self.member], hours=10)
        hours = self.years()[2024].participation
        self.assertEqual((hours['unit']['hours']['operation'], hours['people']['hours']['operation']),
                         ({'weekday': 1, 'weekend': 9}, {'weekday': 0, 'weekend': 10}))

    def test_each_day_is_a_weekday_or_weekend_in_its_own_right(self):
        # Friday noon to Sunday noon: one weekday and two weekend days.
        self.make_event('operation', when(2024, 2, 9), attended=[self.member, self.other], hours=48)
        row = self.years()[2024]
        self.assertEqual(row.participation['unit']['days']['operation'], {'weekday': 1, 'weekend': 2})
        # The event counts once, on the Friday it started.
        self.assertEqual(row.participation['unit']['events']['operation'], {'weekday': 1, 'weekend': 0})
        self.assertEqual(row.participation['people']['events']['operation'], {'weekday': 2, 'weekend': 0})
        self.assertEqual(row.participation['unit']['hours']['operation'], {'weekday': 12, 'weekend': 36})
        self.assertEqual(row.participation['people']['hours']['operation'], {'weekday': 24, 'weekend': 72})

    def test_days_chart_has_a_view_for_the_unit_and_one_for_people(self):
        self.make_event('operation', when(2024, 2, 9), attended=[self.member, self.other], hours=48)
        chart = self.chart('days')
        self.assertEqual([m['label'] for m in chart['measures']], ['Days', 'Events', 'Hours'])
        self.assertEqual([v['label'] for v in chart['views']], ['Unit (any member out)', 'Members (added up)'])
        # Hover text is a heading and a line for each part, for each measure in the order drawn: Hours first.
        self.assertEqual(self.panel('days', 'Operations')['cells'][0]['tips'],
                         [{'head': '2024 to 15 Jun: 48.0 hours',
                           'lines': [{'number': '12.0', 'label': 'on weekdays'},
                                     {'number': '36.0', 'label': 'on weekends'}]},
                          {'head': '2024 to 15 Jun: 3 days', 'lines': [{'number': '1', 'label': 'on weekdays'},
                                                                       {'number': '2', 'label': 'on weekends'}]},
                          {'head': '2024 to 15 Jun: 1 event', 'lines': [{'number': '1', 'label': 'on weekdays'},
                                                                        {'number': '0', 'label': 'on weekends'}]}])
        self.assertEqual([self.tips('days', 'Operations', measure=m, view=1)[0]
                          for m in ('Days', 'Events', 'Hours')],
                         ['2024 to 15 Jun: 6 member-days | 2 on weekdays | 4 on weekends',
                          '2024 to 15 Jun: 2 events attended | 2 on weekdays | 0 on weekends',
                          '2024 to 15 Jun: 96.0 member-hours | 24.0 on weekdays | 72.0 on weekends'])
        # The weekend is the darker part, at the foot of the column; the key reads weekday, weekend.
        self.assertEqual([(p['colour'], p['sizes'][0] > 50) for p in
                          self.panel('days', 'Operations')['cells'][0]['parts']], [('1', True), ('1-light', False)])
        self.assertEqual([(k['colour'], k['label']) for k in self.panel('days', 'Operations')['key']],
                         [('1-light', 'Weekday'), ('1', 'Weekend')])

    def test_an_entry_too_long_to_be_right_is_a_day_without_hours(self):
        self.make_event('training', when(2024, 2, 10), attended=[self.member], hours=24 * 30)
        row = self.years()[2024]
        self.assertEqual(row.participation['unit']['days']['training'], {'weekday': 0, 'weekend': 1})
        self.assertEqual(row.participation['unit']['hours']['training'], {'weekday': 0, 'weekend': 0})
        self.assertEqual(row.participation['people']['hours']['training'], {'weekday': 0, 'weekend': 0})

    def test_seven_days_by_the_local_clock_are_not_too_long_in_the_week_the_clocks_go_back(self):
        # Noon on 1 Nov 2023 to noon on 8 Nov by the clock in California: 7 days and an hour passed.
        self.make_event('training', datetime(2023, 11, 1, 19, 0, tzinfo=dt_timezone.utc), attended=[self.member],
                        hours=7 * 24 + 1)
        row = self.years()[2023]
        self.assertEqual(sum(row.participation['unit']['days']['training'].values()), 8)
        self.assertEqual(round(sum(row.participation['people']['hours']['training'].values())), 7 * 24 + 1)
        self.assertEqual(round(sum(row.participation['unit']['hours']['training'].values())), 7 * 24 + 1)

    def test_ahc_time_is_peoples_but_not_the_units(self):
        self.make_event('operation', when(2024, 2, 7), ahc=[self.member])
        row = self.years()[2024]
        self.assertEqual(row.participation['unit']['days']['operation'], {'weekday': 0, 'weekend': 0})
        self.assertEqual(row.participation['unit']['hours']['operation'], {'weekday': 0, 'weekend': 0})
        self.assertEqual(row.participation['people']['days']['operation'], {'weekday': 1, 'weekend': 0})
        self.assertEqual(row.participation['people']['hours']['operation'], {'weekday': 2, 'weekend': 0})

    def test_operations_by_responders_and_called_off(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], ahc=[self.other])
        self.make_event('operation', when(2024, 2, 8), attended=[self.member, self.other, self.third])
        self.make_event('operation', when(2024, 2, 9), attended=[self.member, self.other, self.third,
                                                                 self.make_member('Dee', 'T')])
        # Each of these had a callout page; nobody but the AHC or a guest went.
        for called_off in (self.make_event('operation', when(2024, 2, 10), no_time=[self.member, self.other]),
                           self.make_event('operation', when(2024, 2, 11), ahc=[self.member]),        # only the AHC
                           self.make_event('operation', when(2024, 2, 12), attended=[self.make_member('Gus', 'G')]),
                           self.make_event('operation', when(2024, 6, 10), no_time=[self.member]),    # five days ago
                           self.make_event('operation', when(2024, 6, 14), no_time=[self.member]),    # yesterday
                           # Under way with no time logged yet: counted once it has finished.
                           self.make_event('operation', NOW - timedelta(hours=1), no_time=[self.member])):
            self.page(called_off, called_off.start_at - timedelta(hours=1), 'Callout', 'Available?', {})
        self.assertEqual(self.years()[2024].operations,
                         {'thin': 2, 'middling': 1, 'full': 0, 'called_off': 5, 'heads_up': 0})
        # The operations that ran are those the member page counts.
        self.assertEqual(len(unit_rows(NOW)['responded']), len(operations_that_ran(NOW, every_operation())))

    def test_an_operation_that_never_became_a_callout_was_a_heads_up_only(self):
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
        def operation(day, pages=(), went=()):
            event = self.make_event('operation', when(2024, 2, day), no_time=[self.member], attended=list(went))
            for hours_before, (text, template) in zip((3, 2), pages):
                self.page(event, when(2024, 2, day) - timedelta(hours=hours_before), text, template, {self.member: 60})
        operation(5, [('Heads up: search', 'Heads Up')])                                        # heads-up only
        operation(6)                                                                            # no page at all
        operation(7, [('Heads up: search', 'Heads Up'), ('Callout: search', 'Available?')])     # called off
        operation(8, [('Heads up: search', 'Heads Up')], went=[self.other])                     # ran all the same
        self.make_event('operation', when(2022, 2, 7), attended=[self.other])    # so that 2019 is no stray record
        # Before 13 Feb 2019 pages do not say which they are: called off, whatever was sent, unless the title
        # calls it a heads-up.
        before = self.make_event('operation', when(2019, 2, 12), no_time=[self.member])
        self.page(before, when(2019, 2, 12) - timedelta(hours=3), 'Heads up: search', None, {self.member: 60})
        titled = self.make_event('operation', when(2019, 2, 10), no_time=[self.member])
        Event.objects.filter(id=titled.id).update(title='Ridge search (heads up)')
        years = self.years()
        self.assertEqual(years[2024].operations,
                         {'thin': 1, 'middling': 0, 'full': 0, 'called_off': 1, 'heads_up': 2})
        self.assertEqual(years[2019].operations,
                         {'thin': 0, 'middling': 0, 'full': 0, 'called_off': 1, 'heads_up': 1})
        tips = self.tips('operations', '')
        self.assertEqual(tips[-1], '2024 to 15 Jun: 4 operations | 1 ran | 1 with 1 to 3 responders | 0 with 4 to 7 '
                                   '| 0 with 8 or more | 1 called off | 2 heads-up only')
        self.assertEqual(tips[0], '2019: 2 operations | 0 ran | 0 with 1 to 3 responders | 0 with 4 to 7 '
                                  '| 0 with 8 or more | 1 called off | 1 heads-up only '
                                  '| Before 13 Feb, heads-ups told by their titles')
        # Two greys above the blues, the lighter on top.
        self.assertEqual([p['colour'] for p in self.panel('operations', '')['cells'][-1]['parts']],
                         ['1-light', 'muted-light', 'total'])
        self.assertEqual([k['label'] for k in self.panel('operations', '')['key']][-2:],
                         ['Called off', 'Heads-up only'])

    def test_with_no_page_ever_saying_which_it_was_the_title_tells_a_heads_up(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        quiet = self.make_event('operation', when(2024, 3, 7), no_time=[self.member])
        self.page(quiet, when(2024, 3, 7), 'Search', None, {self.member: 60})          # no reply template
        titled = self.make_event('operation', when(2024, 4, 7), no_time=[self.member])
        Event.objects.filter(id=titled.id).update(title='Ridge search (heads up)')
        self.assertIsNone(unit_rows(NOW)['templates_from'])
        self.assertEqual((self.years()[2024].operations['called_off'], self.years()[2024].operations['heads_up']),
                         (1, 1))
        self.assertEqual([k['label'] for k in self.panel('operations', '')['key']][-2:],
                         ['Called off', 'Heads-up only'])
        self.assertEqual(self.tips('operations', '')[-1].split(' | ')[-3:],
                         ['1 called off', '1 heads-up only', 'Heads-ups told by their titles'])
        not_run = 'The operation has finished with no member other than the AHC having a day attended on it up to today'
        glossary = dict(unit_activity(NOW)['glossary'])
        self.assertEqual((glossary['Called off'], glossary['Heads-up only']),
                         (not_run + ', and its title does not call it a heads-up.',
                          not_run + ', and its title calls it a heads-up.'))

    def test_a_team_names_the_reply_template_of_its_heads_up_pages(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(event, when(2024, 2, 7) - timedelta(hours=6), 'Warning: search', 'Warning', {self.member: 60})
        self.page(event, when(2024, 2, 7) - timedelta(hours=5), 'Heads up: search', 'Heads Up', {self.other: 60})
        with override_settings(ACTIVITY_REPORTS={'HEADS_UP_TEMPLATE': 'Warning'}):
            # The 06:00 page, the team's heads-up, is a callout page; the 07:00 one is not.
            self.assertEqual(unit_rows(NOW)['reply_hours'], {(date(2024, 2, 7), 6, 'minutes'): 1})

    def test_a_teams_heads_up_template_tells_an_operation_only_warned_of(self):
        # An operation that did not run, with a plain title, whose only page carries the reply template
        # 'Warning'. By default no page has yet said which it was, so its title decides: called off. Where
        # 'Warning' is the team's heads-up template, its pages decide from that page on: only a heads-up.
        operation = self.make_event('operation', when(2024, 2, 7), no_time=[self.member])
        self.page(operation, when(2024, 2, 7) - timedelta(hours=1), 'Search', 'Warning', {self.member: 60})
        for rules, outcome in (({}, (1, 0)), ({'HEADS_UP_TEMPLATE': 'Warning'}, (0, 1))):
            with override_settings(ACTIVITY_REPORTS=rules):
                operations = self.years()[2024].operations
                self.assertEqual((operations['called_off'], operations['heads_up']), outcome, rules)

    def test_test_and_demo_events_and_operations_never_used_count_nowhere(self):
        def event(event_type, day, title, **people):
            made = self.make_event(event_type, when(2024, 2, day), **people)
            Event.objects.filter(id=made.id).update(title=title)
            return made
        self.paging_began()        # pages recorded from the usual day: a demonstration's page does not move it
        event('operation', 7, 'Search', attended=[self.member])                       # counts
        event('training', 8, 'TEST', attended=[self.member])
        demo = event('operation', 9, 'Demo Event - Somewhere', attended=[self.other])
        self.page(demo, when(2024, 2, 9) - timedelta(hours=1), 'Callout', 'Available?', {self.member: 60})
        event('meeting', 10, '[radio] Test Event', attended=[self.other])
        event('operation', 12, 'Ridge rescue')                                         # never used
        event('operation', 13, "Hollow Creek search (head's up)")                     # a heads-up all the same
        row = self.years()[2024]
        self.assertEqual(row.operations, {'thin': 1, 'middling': 0, 'full': 0, 'called_off': 0, 'heads_up': 1})
        self.assertEqual({t: sum(row.participation['people']['days'][t].values()) for t in TYPES},
                         {'operation': 1, 'training': 0, 'meeting': 0, 'community': 0})
        self.assertEqual(sum(row.replies.values()), 0)
        self.assertEqual(len(unit_rows(NOW)['first_pages']), 0)

    def test_an_event_of_a_type_the_reports_do_not_show_counts_nowhere(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        other = self.make_event('training', when(2024, 2, 8), attended=[self.member])
        Event.objects.filter(id=other.id).update(type='other')
        row = self.years()[2024]
        self.assertEqual({t: sum(row.participation['people']['days'][t].values()) for t in TYPES},
                         {'operation': 1, 'training': 0, 'meeting': 0, 'community': 0})
        self.assertEqual(unit_activity(NOW)['period'], '2024 to 15 Jun 2024')

    def test_events_count_whether_published_or_not(self):
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
        on_calendar = self.make_event('training', when(2024, 3, 4), attended=[self.member])
        on_calendar.published = True
        on_calendar.save()
        self.make_event('training', when(2024, 3, 5), attended=[self.member, self.other])
        self.make_event('operation', when(2024, 3, 6), no_time=[self.member])           # no page: a heads-up only
        self.assertFalse(Event.objects.get(start_at=when(2024, 3, 5)).published)
        row = self.years()[2024]
        self.assertEqual(row.participation['unit']['events']['training'], {'weekday': 2, 'weekend': 0})
        self.assertEqual(row.participation['people']['days']['training'], {'weekday': 3, 'weekend': 0})
        self.assertEqual(row.operations['heads_up'], 1)

    def test_a_repage_listing_its_pages_between_slashes_is_in_their_chain(self):
        # Some messages in the database list the pages before them between slashes, as "12/34".
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        sent = when(2024, 2, 7) - timedelta(hours=6)
        first = self.page(event, sent, 'Callout: search', 'Available?', {self.member: 600})
        repage = self.page(event, sent + timedelta(minutes=5), 'Repage: Callout: search', 'Available?',
                           {self.member: 300}, repage_of=[first])
        Message.objects.filter(id=repage.id).update(ancestry='{}/'.format(first.id))
        self.assertEqual(sum(self.years()[2024].replies.values()), 1)

    def test_the_year_menus_start_where_the_page_does_and_list_years_with_data(self):
        stray = self.make_event('operation', when(1995, 2, 7), attended=[self.member])
        for year in (2022, 2024):
            event = self.make_event('operation', when(year, 2, 7), attended=[self.member, self.other])
            self.page(event, when(year, 2, 7) - timedelta(hours=6), 'Callout', 'Available?', {self.member: 60})
        self.page(stray, when(1995, 2, 7) - timedelta(hours=6), 'Callout', 'Available?', {self.member: 60})
        for name in ('responders', 'calls', 'reply_hours'):
            chart = self.chart(name)
            self.assertEqual([o['label'] for o in chart['menu']['options']], ['All years', '2024', '2022'], name)
            self.assertTrue(chart['measures'][0]['title'].endswith(', 2022 to Present'), name)
        # The 1995 operation, a stray, is in no column; 1 responder would be its only one.
        self.assertEqual(self.drawn('responders', ''), [False, True])

    def test_an_operation_whose_only_time_is_dated_after_today_was_called_off(self):
        slip = self.make_event('operation', when(2024, 3, 7), no_time=[self.other])
        self.page(slip, when(2024, 3, 7), 'Callout', 'Available?', {})
        Participant.objects.create(period=slip.period_set.first(), member=self.member,
                                   en_route_at=when(2025, 3, 7), return_home_at=when(2025, 3, 7) + timedelta(hours=4))
        self.assertEqual(self.years()[2024].operations,
                         {'thin': 0, 'middling': 0, 'full': 0, 'called_off': 1, 'heads_up': 0})
        self.assertEqual(operations_that_ran(NOW, every_operation()), set())     # the member page's rule, the same one

    def test_days_on_operations_by_responders_that_day(self):
        # Two went for the Friday and the Saturday; two more joined them on the Saturday, on another operation.
        self.make_event('operation', when(2024, 2, 9), attended=[self.member], ol=[self.other], hours=30)
        self.make_event('operation', when(2024, 2, 10), attended=[self.third, self.make_member('Dee', 'T')])
        row = self.years()[2024]
        self.assertEqual(row.operations, {'thin': 2, 'middling': 0, 'full': 0, 'called_off': 0, 'heads_up': 0})
        # On the Friday two were out; on the Saturday four were, across the two operations.
        self.assertEqual(sorted(size for _, size in unit_rows(NOW)['day_responded']), [2, 4])
        self.assertEqual(row.operation_days, {'thin': 1, 'middling': 1, 'full': 0})
        self.assertEqual([m['title'] for m in self.chart('operations')['measures']],
                         ['Operations, by unique responder count, 2024',
                          'Operation days, by unique responder count, 2024'])

    def test_a_team_sets_how_many_responders_are_few_and_how_many_many(self):
        dee = self.make_member('Dee', 'T')
        for day, went in ((7, [self.member, self.other]), (14, [self.member, self.other, self.third]),
                          (21, [self.member, self.other, self.third, dee])):
            self.make_event('operation', when(2024, 2, day), attended=went)
        with override_settings(ACTIVITY_REPORTS={'RESPONDERS_THIN': 2, 'RESPONDERS_FULL': 4}):
            row = self.years()[2024]
            self.assertEqual((row.operations, row.operation_days),
                             ({'thin': 1, 'middling': 1, 'full': 1, 'called_off': 0, 'heads_up': 0},
                              {'thin': 1, 'middling': 1, 'full': 1}))
            self.assertEqual([k['label'] for k in self.panel('operations', '')['key']][:3],
                             ['1 to 2 responders', '3 to 3', '4 or more'])

    def test_responders_on_each_operation_and_each_day(self):
        self.make_event('operation', when(2020, 2, 7), attended=[self.member], ahc=[self.other])
        self.make_event('operation', when(2023, 2, 7), attended=[self.member, self.other, self.third])
        self.make_event('operation', when(2024, 2, 7), attended=[self.member, self.third], ol=[self.other],
                        hours=30)
        self.make_event('operation', when(2024, 3, 7), no_time=[self.member])
        chart = self.chart('responders')
        # A menu picks what is added up: every year on record, shown first, or one year with operations.
        self.assertEqual(chart['menu']['label'], 'Year')
        self.assertEqual([(o['label'], o['selected']) for o in chart['menu']['options']],
                         [('All years', True), ('2024', False), ('2023', False), ('2020', False)])
        self.assertEqual([o['chart']['measures'][0]['title'] for o in chart['menu']['options']][:3],
                         ['Operations at each responder count, 2020 to Present',
                          'Operations at each responder count, 2024',
                          'Operations at each responder count, 2023'])
        # The switch reads "Count: Operations | Days", naming what the columns count.
        self.assertEqual((chart['view_switch_label'], [v['label'] for v in chart['views']]),
                         ('Count', ['Operations', 'Days']))
        # Every chart has a key, even with one series: it names what the columns count.
        self.assertEqual([[k['label'] for k in v['panels'][0]['key']] for v in chart['views']],
                         [['Operations'], ['Operation days']])
        for drawn in unit_activity(NOW)['charts']:
            for view in drawn['views']:
                for panel in view['panels']:
                    self.assertTrue(panel['key'], drawn['name'])
        self.assertIn('Operation days at each responder count, 2020 to Present',
                      [t['text'] for t in chart['titles']])
        self.assertEqual(len(chart['views'][0]['panels']), 1)
        self.assertEqual(self.tips('responders', ''),
                         ['1 responder: 1 operation | since 2020', '2 responders: 0 operations | since 2020',
                          '3 responders: 2 operations | since 2020'])
        # In 2024, only the operation of that February; every option has the same columns.
        self.assertEqual(self.drawn('responders', '', option='2024'), [False, False, True])
        self.assertEqual(self.drawn('responders', '', option='2020'), [True, False, False])
        # The days: one in 2020 with one out, one in 2023 with three, and the two days of February 2024.
        self.assertEqual(sorted(size for _, size in unit_rows(NOW)['day_responded']), [1, 3, 3, 3])

    def test_whoever_led_is_one_of_the_members_who_attended(self):
        self.make_event('operation', when(2023, 2, 7), attended=[self.member], ol=[self.other])
        self.make_event('operation', when(2023, 3, 7), attended=[self.member, self.other], ahc=[self.third])
        self.make_event('operation', when(2024, 2, 7), ol=[self.other])
        self.make_event('operation', when(2024, 3, 7), ahc=[self.member])                     # called off
        self.make_event('training', when(2024, 4, 7), attended=[self.third, self.other], leaders='ann',
                        no_time=[self.member])
        self.make_event('training', when(2024, 4, 8), attended=[self.member], leaders='Bob and Ann')
        years = self.years()
        # Bob led one operation of the two he went on: he counts once, as leading.
        self.assertEqual(years[2023].members['operation'], {'others': 2, 'led': 1})
        self.assertEqual(years[2023].without_ol, 1)
        self.assertEqual(years[2024].members['operation'], {'others': 1, 'led': 1})
        # Ann led on the 8th; on the 7th she was listed without time, so led nothing then.
        self.assertEqual(years[2024].members['training'], {'others': 2, 'led': 1})
        self.assertEqual(self.tips('members', 'Operations'),
                         ['2023: 3 members | 1 as OL | 2 other members | 1 operation with no OL recorded',
                          '2024 to 15 Jun: 2 members | 1 as OL | 1 other member'])
        self.assertEqual(self.tips('members', 'Trainings')[-1],
                         '2024 to 15 Jun: 3 members | 1 as TL or LL | 2 other members')
        self.assertEqual([m['label'] for m in self.chart('members')['measures']],
                         ['Members'])       # their days are on the days chart

    def test_a_member_who_has_since_left_still_led_what_they_led(self):
        # Named in the leaders text in 2024; an alum today. Leading counts whatever their status now.
        alum = self.make_member('Cal', 'MA')
        self.make_event('training', when(2024, 4, 7), attended=[alum, self.member], leaders='Cal')
        self.assertEqual(self.years()[2024].members['training'], {'others': 1, 'led': 1})

    def test_of_time_logged_twice_from_the_same_moment_the_member_reports_event_keeps_it(self):
        # An operation and a training both from noon, the operation entered first: the member report's
        # order gives the shared hours to the operation, and so does this report.
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=4)
        self.make_event('training', when(2024, 2, 7), attended=[self.member], hours=4)
        row = self.years()[2024]
        self.assertEqual({t: sum(row.participation['people']['hours'][t].values()) for t in ('operation', 'training')},
                         {'operation': 4, 'training': 0})

    def test_the_longer_username_is_the_leader_where_two_could_match(self):
        short = self.make_member('Lee', 'TM')
        full = self.make_member('Ann Lee', 'TM')
        self.make_event('training', when(2024, 4, 7), attended=[short, full], leaders='Ann Lee')
        self.assertEqual(self.years()[2024].members['training'], {'others': 1, 'led': 1})
        self.make_event('training', when(2024, 4, 9), attended=[short], leaders='Ann Lee')
        self.assertEqual(self.years()[2024].members['training'], {'others': 1, 'led': 1})

    def test_of_two_usernames_differing_only_in_spacing_the_first_member_is_the_leader(self):
        # The event page links the member who came first; so does this report.
        first = self.make_member('Ann  Lee', 'TM')
        later = self.make_member('Ann Lee', 'TM')
        self.make_event('training', when(2024, 4, 7), attended=[later], leaders='Ann Lee')
        self.assertEqual(self.years()[2024].members['training'], {'others': 1, 'led': 0})
        self.make_event('training', when(2024, 4, 9), attended=[first], leaders='ann lee')
        self.assertEqual(self.years()[2024].members['training'], {'others': 1, 'led': 1})

    def test_status_rows_saved_at_the_same_moment_are_read_in_the_order_saved(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        with CaptureQueriesContext(connection) as queries:
            self.years()
        history = next(q['sql'] for q in queries.captured_queries if 'historicalmember' in q['sql'].lower())
        # Both the window that finds a change of status and the final order break ties by history_id.
        self.assertEqual(history.count('"history_id" ASC'), 2, history)

    def test_a_responder_with_no_recorded_status_counts_as_other(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member, self.third])
        history = Member.history.model.objects
        history.update(history_date=when(2024, 1, 1))
        history.filter(id=self.third.id).delete()            # never saved since history began
        self.assertEqual(self.years()[2024].status_days, {'T': 0, 'FM': 1, 'TM': 0, 'other': 1})
        self.assertEqual(self.years()[2024].status_events, {'T': 0, 'FM': 1, 'TM': 0, 'other': 1})

    def test_responders_by_the_status_they_held_on_the_day(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member, self.third], ahc=[self.other])
        self.third.status = 'FM'
        self.third.save()
        self.make_event('operation', when(2024, 6, 14), attended=[self.member, self.third,
                                                                  self.make_member('Dee', 'R')])
        history = Member.history.model.objects
        history.update(history_date=when(2024, 1, 1))
        history.filter(id=self.third.id, status='FM').update(history_date=when(2024, 5, 1))
        self.make_event('operation', when(2023, 6, 14), attended=[self.member])       # before statuses were kept
        self.assertEqual(self.years()[2024].status_days, {'T': 1, 'FM': 3, 'TM': 0, 'other': 1})
        # Saves that leave the status alone, as every login is, change nothing.
        for _ in range(3):
            self.member.save()
        self.assertEqual(self.years()[2024].status_days, {'T': 1, 'FM': 3, 'TM': 0, 'other': 1})
        chart = self.chart('status')
        self.assertEqual(chart['measures'][0]['title'],
                         'Responder-days, by status on the day, 2024')
        # The note is the question alone; when statuses start is in the glossary.
        self.assertEqual(chart['note'], 'How is time in the field split by status?')
        self.assertIn(('Status', 'The status a member held on the day; for operations attended, on the day the '
                                 'operation started. Statuses are recorded from 01 Jan 2024; a member first recorded '
                                 'later is counted under their first recorded status, and one never recorded as '
                                 'Other status.'),
                      unit_activity(NOW)['glossary'])
        self.assertEqual(self.tips('status', '', measure='Days'),
                         ['2024 to 15 Jun: 5 responder-days | 1 Trainee | 3 Field Member | 0 Technical Member '
                          '| 1 Other status'])
        # The hours each logged on those days, by the same statuses.
        self.assertEqual(self.years()[2024].status_hours, {'T': 4, 'FM': 12, 'TM': 0, 'other': 4})
        self.assertEqual(chart['measures'][2]['title'], 'Responder-hours, by status on the day, 2024')
        # Each operation once for each responder, by their status the day it started.
        self.assertEqual(self.years()[2024].status_events, {'T': 1, 'FM': 3, 'TM': 0, 'other': 1})
        self.assertEqual(chart['measures'][1]['title'],
                         'Operations attended, by status at the start, 2024')

    def test_a_team_sets_which_statuses_have_a_band_of_their_own(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member, self.third])     # an FM and a T
        Member.history.model.objects.update(history_date=when(2024, 1, 1))
        with override_settings(ACTIVITY_REPORTS={'BANDED_STATUSES': ('T', 'FM')}):
            self.assertEqual(self.years()[2024].status_days, {'T': 1, 'FM': 1, 'other': 0})
            self.assertEqual([(k['colour'], k['label']) for k in self.panel('status', '')['key']],
                             [('1-light', 'Trainee'), ('1', 'Field Member'), ('muted', 'Other status')])
        with override_settings(ACTIVITY_REPORTS={'BANDED_STATUSES': ('FM',)}):
            self.assertEqual(self.years()[2024].status_days, {'FM': 1, 'other': 1})

    def test_when_operations_are_first_paged(self):
        early = self.make_event('operation', when(2024, 2, 7), attended=[self.member])        # a Wednesday
        self.make_event('operation', when(2024, 2, 20), no_time=[self.member])        # called off, never paged
        for hours in (-6, -3):        # paged at 6 and at 9 that morning: the first counts
            message = Message.objects.create(author=self.member, text='Callout', format='page',
                                             period=early.period_set.first())
            Message.objects.filter(id=message.id).update(created_at=when(2024, 2, 7) + timedelta(hours=hours))
        chart = self.chart('calls')
        self.assertEqual([v['label'] for v in chart['views']], ['Month', 'Day of week', 'Hour'])
        self.assertEqual([k['label'] for k in chart['views'][0]['panels'][0]['key']], ['Operations'])
        self.assertIn('Operations by hour of first page, 2024',
                      [t['text'] for t in chart['titles']])
        self.assertEqual(unit_rows(NOW)['first_pages'], [timezone.localtime(when(2024, 2, 7) - timedelta(hours=6))])
        self.assertEqual(self.tips('calls', '')[:2], ['January: 0 operations | since 2024',
                                                      'February: 1 operation | since 2024'])
        # On a Wednesday, at 06:00.
        self.assertEqual([self.drawn('calls', '', view=view).index(True) for view in (0, 1, 2)], [1, 2, 6])
        self.assertEqual(self.drawn('calls', '', view=2, option='2024').index(True), 6)
        self.assertEqual([o['label'] for o in chart['menu']['options']], ['All years', '2024'])

    def page(self, event, sent, text, template, replies, repage_of=()):
        """Send a page for `event` at `sent`, with the reply template named
        `template`, or none. `replies` maps each member it went to onto the
        seconds they took to reply, or None for no reply. A repage lists the
        pages before it, the first first, as `repage_of`."""
        message = Message.objects.create(author=self.member, text=text, format='page',
                                         period=event.period_set.first(),
                                         rsvp_template=template and RsvpTemplate.objects.get_or_create(name=template)[0],
                                         ancestry=', '.join(str(page.id) for page in repage_of) or None,
                                         linked_rsvp=repage_of[-1] if repage_of else None)
        Message.objects.filter(id=message.id).update(created_at=sent)
        for member, seconds in replies.items():
            Distribution.objects.create(message=message, member=member, rsvp=seconds is not None,
                                        rsvp_answer=None if seconds is None else True, response_seconds=seconds)
        return message

    def test_replies_to_callout_pages_by_how_soon(self):
        guest = self.make_member('Fay', 'G')
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(event, when(2024, 2, 7) - timedelta(hours=6), 'Heads up: search', 'Heads Up',
                  {self.member: 60, self.other: 1200, self.third: None, guest: 30})
        self.page(event, when(2024, 2, 7) - timedelta(hours=3), 'Delayed callout', 'Available?',
                  {self.member: 300, self.other: 2 * 3600})
        self.page(event, when(2024, 2, 7), 'Have you left?', 'Left?', {self.member: 10})      # not a callout page
        answered = Distribution.objects.filter(member=self.third)       # a reply with no time recorded
        self.assertEqual(self.years()[2024].replies,
                         {'minutes': 2, 'hour': 1, 'later': 1, 'untimed': 0, 'none': 1})
        answered.update(rsvp=True)
        self.assertEqual(self.years()[2024].replies['untimed'], 1)
        # A reply timed before its page was sent counts as untimed, rather than as a quick reply.
        Distribution.objects.filter(member=self.member, response_seconds=60).update(response_seconds=-30)
        self.assertEqual(self.years()[2024].replies,
                         {'minutes': 1, 'hour': 1, 'later': 1, 'untimed': 2, 'none': 0})
        Distribution.objects.filter(member=self.member, response_seconds=-30).update(response_seconds=60)
        self.assertEqual(self.tips('replies', ''),
                         ['2024 to 15 Jun: 5 callouts to members | 2 within 5 minutes | 1 over 5, up to 60 minutes '
                          '| 1 over an hour | 1 reply time not recorded | 0 no reply'])
        self.assertEqual([t['text'] for t in self.chart('replies')['titles']],
                         ['Callouts to members, by time to reply, 2024'])
        # By the hour sent, over every year or the one picked: sent at 06:00 and at 09:00 Pacific.
        sent = date(2024, 2, 7)
        self.assertEqual(unit_rows(NOW)['reply_hours'], {(sent, 6, 'minutes'): 1, (sent, 6, 'hour'): 1,
                                                         (sent, 6, 'untimed'): 1, (sent, 9, 'minutes'): 1,
                                                         (sent, 9, 'later'): 1})
        self.assertEqual(self.tips('reply_hours', '')[6],
                         '06:00 to 06:59: 3 callouts to members | 1 within 5 minutes | 1 over 5, up to 60 minutes '
                         '| 0 over an hour | 1 reply time not recorded | 0 no reply | since 2024')
        # A page of 2021 is in all years and not in 2024.
        early = self.make_event('operation', when(2021, 2, 7), attended=[self.member])
        self.page(early, when(2021, 2, 7) - timedelta(hours=6), 'Heads up: search', 'Heads Up', {self.member: 60})
        self.assertEqual(self.figures('reply_hours', '')[6], [2, 1, 0, 1, 0])
        self.assertEqual(self.figures('reply_hours', '', option='2024')[6], [1, 1, 0, 1, 0])
        self.assertEqual(self.chart('reply_hours')['note'],
                         'How soon do members reply to callout pages sent at each hour?')
        menu = self.chart('reply_hours')['menu']['options']
        self.assertEqual([(o['label'], o['chart']['measures'][0]['title']) for o in menu][:2],
                         [('All years', 'Callouts to members, by hour and time to reply, 2021 to Present'),
                          ('2024', 'Callouts to members, by hour and time to reply, 2024')])

    def test_a_team_sets_how_soon_a_reply_or_a_departure_is_quick(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(event, when(2024, 2, 7) - timedelta(hours=6), 'Callout', 'Available?',
                  {self.member: 30, self.other: 300, self.third: 1200})
        for month, minutes in ((3, 5), (4, 15), (5, 30)):
            sent = when(2024, month, 7)
            out = self.make_event('operation', sent + timedelta(minutes=minutes), attended=[self.member])
            self.page(out, sent, 'Immediate callout', 'Available?', {})
        with override_settings(ACTIVITY_REPORTS={'REPLY_MINUTES': (1, 10), 'DEPARTURE_MINUTES': (10, 20)}):
            row = self.years()[2024]
            self.assertEqual(row.replies, {'minutes': 1, 'hour': 1, 'later': 1, 'untimed': 0, 'none': 0})
            self.assertEqual(row.first_out, {'half': 1, 'hour': 1, 'later': 1, 'none': 0})
            self.assertEqual([k['label'] for k in self.panel('replies', '')['key']][:3],
                             ['Within 1 minute', 'Over 1, up to 10 minutes', 'Over 10 minutes'])
            self.assertEqual([k['label'] for k in self.panel('immediate', '')['key']][:3],
                             ['Within 10 minutes', 'Over 10, up to 20 minutes', 'Over 20 minutes'])

    def test_a_page_and_its_repages_count_once_for_each_member_timed_from_the_first(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        dee = self.make_member('Dee', 'T')
        sent = when(2024, 2, 7) - timedelta(hours=6)                      # 06:00 Pacific
        # A reply to a repage is marked on every page before it too, timed from each page.
        first = self.page(event, sent, 'Callout: search', 'Available?',
                          {self.member: 60, self.other: 720, self.third: 7230})
        again = self.page(event, sent + timedelta(minutes=10), 'Repage: Callout: search', 'Available?',
                          {self.other: 120, self.third: 6630, dee: 60}, repage_of=[first])
        self.page(event, sent + timedelta(hours=2), 'Repage: Repage: Callout: search', 'Available?',
                  {self.third: 30}, repage_of=[first, again])
        # Dee was paged first by the repage, and is timed from it.
        self.assertEqual(self.years()[2024].replies,
                         {'minutes': 2, 'hour': 1, 'later': 1, 'untimed': 0, 'none': 0})
        self.assertEqual(unit_rows(NOW)['reply_hours'], {(date(2024, 2, 7), 6, 'minutes'): 2,
                                                         (date(2024, 2, 7), 6, 'hour'): 1,
                                                         (date(2024, 2, 7), 6, 'later'): 1})
        # A reply on the repage alone, not marked on the page before it, is timed from the first page too.
        Distribution.objects.filter(message=first, member=self.third).update(rsvp=False, response_seconds=None)
        Distribution.objects.filter(message=again, member=self.third).update(rsvp=False, response_seconds=None)
        self.assertEqual(self.years()[2024].replies['later'], 1)

    def test_immediate_callouts_by_how_soon_the_first_responder_left(self):
        def callout(month, text, left_after=None):
            start = when(2024, month, 7)
            event = self.make_event('operation', start + (left_after or timedelta()),
                                    **({'attended': [self.member]} if left_after else {'ahc': [self.member]}))
            self.page(event, start, text, 'Available?', {self.member: 60})
            return event

        callout(1, 'IMMEDIATE callout: search', timedelta(minutes=20))
        slow = callout(2, 'Repage: Immediate callout', timedelta(minutes=90))
        callout(3, 'Immediate: rescue')                                  # nobody but the AHC logged time
        callout(4, 'Delayed callout, not immediate', timedelta(minutes=10))
        # The clock runs from the first immediate page; a later one leaves it running.
        self.page(slow, when(2024, 2, 7) + timedelta(minutes=80), 'Immediate callout', 'Available?', {})
        self.assertEqual(self.years()[2024].first_out, {'half': 1, 'hour': 0, 'later': 1, 'none': 1})
        self.assertEqual(self.tips('immediate', ''),
                         ['2024 to 15 Jun: 3 callouts | 1 within 30 minutes | 0 over 30, up to 60 minutes '
                          '| 1 over an hour | 1 no departure logged after the page'])
        # The clock stops at the first departure after the page: one five hours before it was not in answer to it.
        out = self.make_event('operation', when(2024, 5, 7), attended=[self.member])
        self.page(out, when(2024, 5, 7) + timedelta(hours=5), 'Immediate callout: more needed', 'Available?', {})
        self.assertEqual(self.years()[2024].first_out, {'half': 1, 'hour': 0, 'later': 1, 'none': 2})
        self.assertEqual(self.chart('immediate')['measures'][0]['title'],
                         'Immediate callouts, by time to first departure, 2024')

    def test_a_guests_departure_and_one_after_today_are_left_out(self):
        # An immediate page at noon: a guest left at 12:10 and a member at 12:45, so the first departure is 12:45.
        event = self.make_event('operation', when(2024, 2, 7), no_time=[self.member])
        self.page(event, when(2024, 2, 7), 'Immediate callout', 'Available?', {})
        Participant.objects.filter(period=event.period_set.first(), member=self.member).update(
            en_route_at=when(2024, 2, 7) + timedelta(minutes=45))
        Participant.objects.create(period=event.period_set.first(), member=self.make_member('Fay', 'G'),
                                   en_route_at=when(2024, 2, 7) + timedelta(minutes=10))
        self.assertEqual(self.years()[2024].first_out, {'half': 0, 'hour': 1, 'later': 0, 'none': 0})
        # An immediate page yesterday, and the one departure logged typed for a day after today: none yet.
        coming = self.make_event('operation', when(2024, 6, 14), no_time=[self.member])
        self.page(coming, when(2024, 6, 14), 'Immediate callout', 'Available?', {})
        Participant.objects.filter(period=coming.period_set.first()).update(en_route_at=NOW + timedelta(days=2))
        self.assertEqual(self.years()[2024].first_out, {'half': 0, 'hour': 1, 'later': 0, 'none': 1})

    def test_pages_for_events_other_than_operations_are_not_callout_pages(self):
        training = self.make_event('training', when(2024, 2, 7), attended=[self.member])
        self.page(training, when(2024, 2, 7) - timedelta(hours=1), 'Immediate callout', 'Available?', {self.member: 60})
        rows = unit_rows(NOW)
        self.assertEqual((sum(rows['years'][2024].replies.values()), sum(rows['years'][2024].first_out.values()),
                          rows['reply_hours']), (0, 0, {}))

    def test_a_departure_counts_before_its_member_logs_a_return(self):
        # An immediate page at noon; two members logged as left, at 12:45 and 12:10, and nothing more yet.
        event = self.make_event('operation', when(2024, 2, 7), no_time=[self.member])
        self.page(event, when(2024, 2, 7), 'Immediate callout', 'Available?', {self.member: 60})
        period = event.period_set.first()
        Participant.objects.filter(period=period, member=self.member).update(
            en_route_at=when(2024, 2, 7) + timedelta(minutes=45))
        Participant.objects.create(period=period, member=self.other, en_route_at=when(2024, 2, 7) + timedelta(minutes=10))
        self.assertEqual(self.years()[2024].first_out, {'half': 1, 'hour': 0, 'later': 0, 'none': 0})

    def test_the_same_time_logged_on_two_periods_is_not_a_long_day(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=7)
        second = Period.objects.create(event=event, position=2)
        Participant.objects.create(period=second, member=self.member, en_route_at=when(2024, 2, 7),
                                   return_home_at=when(2024, 2, 7) + timedelta(hours=7))
        self.assertEqual(self.years()[2024].runs, {'day': 1, 'long_day': 0, 'two': 0, 'more': 0})

    def test_twelve_hours_logged_in_three_parts_are_not_a_long_day(self):
        # 8am to 8pm on three periods, one after another: 31 minutes, 2 hours 13 minutes and 9 hours 16 minutes,
        # which added up as fractions of an hour come to a little over 12.
        start = when(2024, 2, 7) - timedelta(hours=4)
        event = self.make_event('operation', start, hours=12)
        periods = [event.period_set.first()] + [Period.objects.create(event=event, position=n) for n in (2, 3)]
        for period, (begins, minutes) in zip(periods, ((0, 31), (31, 133), (164, 556))):
            Participant.objects.create(period=period, member=self.member, en_route_at=start + timedelta(minutes=begins),
                                       return_home_at=start + timedelta(minutes=begins + minutes))
        self.assertEqual(self.years()[2024].runs, {'day': 1, 'long_day': 0, 'two': 0, 'more': 0})

    def test_time_logged_within_other_time_counts_once(self):
        # Thirteen hours from noon, and on a second period two of those hours again: still 13 hours.
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=13)
        Participant.objects.create(period=Period.objects.create(event=event, position=2), member=self.member,
                                   en_route_at=when(2024, 2, 7) + timedelta(hours=1),
                                   return_home_at=when(2024, 2, 7) + timedelta(hours=3))
        row = self.years()[2024]
        self.assertEqual(row.runs, {'day': 0, 'long_day': 1, 'two': 0, 'more': 0})
        self.assertEqual(sum(row.participation['unit']['hours']['operation'].values()), 13)

    def test_time_logged_twice_counts_once_for_the_entry_that_began_first(self):
        # An operation from noon to 4pm and a training from 2pm to 6pm: the two hours they share are the
        # operation's. Each keeps its day, and the unit was out on each for all of its time.
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=4)
        self.make_event('training', when(2024, 2, 7) + timedelta(hours=2), attended=[self.member], hours=4)
        # A meeting logged on two periods at the same times.
        meeting = self.make_event('meeting', when(2024, 3, 6), attended=[self.member], hours=2)
        Participant.objects.create(period=Period.objects.create(event=meeting, position=2), member=self.member,
                                   en_route_at=when(2024, 3, 6), return_home_at=when(2024, 3, 6) + timedelta(hours=2))
        row = self.years()[2024]
        self.assertEqual({t: sum(row.participation['people']['hours'][t].values()) for t in TYPES},
                         {'operation': 4, 'training': 2, 'meeting': 2, 'community': 0})
        self.assertEqual({t: sum(row.participation['people']['days'][t].values()) for t in TYPES},
                         {'operation': 1, 'training': 1, 'meeting': 1, 'community': 0})
        self.assertEqual({t: sum(row.participation['unit']['hours'][t].values()) for t in TYPES},
                         {'operation': 4, 'training': 4, 'meeting': 2, 'community': 0})

    def test_stretches_in_the_field_by_days_in_a_row(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], ahc=[self.other])
        # Thirteen hours from noon: one day, the hour past midnight going with it, and a long day.
        self.make_event('operation', when(2024, 2, 20), attended=[self.other], hours=13)
        for day in (7, 8, 9):                                            # three days running, on two operations
            self.make_event('operation', when(2024, 3, day), attended=[self.third])
        self.make_event('operation', when(2024, 3, 11), attended=[self.third], hours=30)   # after a day's break
        self.make_event('operation', when(2024, 4, 1), attended=[self.member], hours=24 * 9)   # too long to be right
        self.make_event('training', when(2024, 4, 20), attended=[self.member], hours=13)
        self.assertEqual(self.years()[2024].runs, {'day': 1, 'long_day': 1, 'two': 1, 'more': 1})
        # The nine days logged on 1 April are in none of them, as the glossary says.
        self.assertTrue(dict(unit_activity(NOW)['glossary'])['Stretch'].endswith(
            'More than 7 days logged by one member for one event or operating period is left out.'))
        self.assertEqual(self.tips('runs', ''),
                         ['2024 to 15 Jun: 4 stretches | 1 of one day, up to 12 hours | 1 of one day, over 12 hours '
                          '| 1 of 2 days | 1 of 3 or more days'])
        self.assertEqual([k['label'] for k in self.chart('runs')['views'][0]['panels'][0]['key']],
                         ['1 day, up to 12 hours', '1 day, over 12 hours', '2 days', '3 or more days'])

    def test_a_team_sets_how_many_hours_make_a_long_day(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=7)
        with override_settings(ACTIVITY_REPORTS={'LONG_DAY': 6}):
            self.assertEqual(self.years()[2024].runs, {'day': 0, 'long_day': 1, 'two': 0, 'more': 0})
            self.assertEqual([k['label'] for k in self.panel('runs', '')['key']][:2],
                             ['1 day, up to 6 hours', '1 day, over 6 hours'])
        with override_settings(ACTIVITY_REPORTS={'LONG_DAY': 1}):
            self.assertEqual([k['label'] for k in self.panel('runs', '')['key']][:2],
                             ['1 day, up to 1 hour', '1 day, over 1 hour'])

    def members_coming_and_going(self):
        """Ann, there as the records start in 2020, gone for more than 12 months, back in 2024. Bob, who
        joined in 2021 on his third operation and has had no day since March 2023. Cat, who came to SAR
        Basic, a guest training and two others in 2023 and joined at her third member training, in 2024.
        Dee (one meeting) and Eve (a community event and a guest training), who with fewer than three
        member-only days joined at their first event, in 2022, and have since left."""
        for day in (7, 14, 21):
            self.make_event('training', when(2020, 3, day), attended=[self.member])
        self.make_event('training', when(2024, 2, 7), attended=[self.member])
        for start in (when(2021, 5, 7), when(2021, 6, 7), when(2021, 7, 7), when(2022, 4, 7), when(2023, 3, 7)):
            self.make_event('operation', start, attended=[self.other])
        for start, title in ((when(2023, 8, 19), 'SAR Basic'), (when(2023, 9, 9), 'Map and compass *G'),
                             (when(2023, 10, 7), 'Sign cutting'), (when(2023, 11, 4), 'Snow *'),
                             (when(2024, 1, 7), 'Steep slopes *')):
            event = self.make_event('training', start, attended=[self.third])
            Event.objects.filter(id=event.id).update(title=title)
        self.make_event('meeting', when(2022, 6, 7), attended=[self.make_member('Dee', 'FM')])
        visitor = self.make_member('Eve', 'MA')
        self.make_event('community', when(2022, 6, 7), attended=[visitor])
        event = self.make_event('training', when(2022, 7, 7), attended=[visitor])
        Event.objects.filter(id=event.id).update(title='Mock rescue G')
        return self.years()

    def test_a_member_is_active_through_the_year_of_their_last_day(self):
        years = self.members_coming_and_going()
        # By the year they joined: Ann in 2020 and again in 2024, Bob 2021 to 2023, Dee and Eve in 2022, Cat 2024.
        self.assertEqual([{joined: n for joined, n in years[y].active.items() if n}
                          for y in (2020, 2021, 2022, 2023, 2024)],
                         [{2020: 1}, {2021: 1}, {2021: 1, 2022: 2}, {2021: 1}, {2020: 1, 2024: 1}])

    def test_who_joined_who_left_and_who_came_back(self):
        years = self.members_coming_and_going()
        nobody = {'joined': 0, 'came_back': 0, 'left': 0, 'left_returned': 0}
        # Nobody is known to have joined as the records start.
        self.assertEqual([years[y].flows[12] for y in (2020, 2021, 2022, 2023, 2024)],
                         [dict(nobody, left_returned=1), dict(nobody, joined=1), dict(nobody, joined=2, left=2),
                          dict(nobody, left=1), dict(nobody, joined=1, came_back=1)])
        # Read at 24 months, Bob is still active: his last day was 15 months ago. Ann still left and came back.
        self.assertEqual([years[y].flows[24] for y in (2020, 2023)], [dict(nobody, left_returned=1), nobody])
        # At 36 months neither Dee nor Eve, last there in 2022, has left yet; Ann had, in 2020.
        self.assertEqual([years[y].flows[36] for y in (2020, 2022)],
                         [dict(nobody, left_returned=1), dict(nobody, joined=2)])
        # Who left in a year is known once that many months have passed since its end.
        self.assertEqual([years[y].left_known for y in (2020, 2021, 2022, 2023)],
                         [{12: True, 24: True, 36: True}, {12: True, 24: True, 36: False},
                          {12: True, 24: False, 36: False}, {12: False, 24: False, 36: False}])

    def test_the_net_change_dot_is_the_sum_of_its_columns_bars(self):
        years = self.members_coming_and_going()
        from main.lib import charts
        with mock.patch('main.lib.unit_activity.charts.share_panels', wraps=charts.share_panels) as drawn:
            unit_activity(NOW)
        views = next(c.args[1] for c in drawn.call_args_list if c.kwargs['name'] == 'flows')
        dots = []
        for view in views:
            for cell in view['series'][0]['cells']:
                entry = cell[0]
                if entry['marker'] is not None:
                    self.assertEqual(entry['marker'], sum(value for _, value in entry['parts']))
                    dots.append(entry['marker'])
        self.assertEqual(len(dots), 3 + 2 + 1)          # the years whose leavers are known, at 12, 24 and 36 months
        # The dot is that year's: in 2022 two joined and two left, though active members went from 1 to 3,
        # because whoever left in 2022 was still active in it.
        self.assertEqual(views[0]['series'][0]['cells'][2][0]['marker'], 0)
        self.assertEqual([sum(years[y].active.values()) for y in (2021, 2022)], [1, 3])
        self.assertIn('the net change dot and the active-members chart show their leaving a year apart',
                      dict(unit_activity(NOW)['glossary'])['Left'])

    def test_who_left_in_a_year_is_known_the_day_a_member_last_there_on_its_last_day_has_left(self):
        self.make_event('training', when(2023, 1, 9), attended=[self.member, self.other])
        self.make_event('training', when(2023, 12, 31), attended=[self.member])      # a Sunday, local time
        self.make_event('training', when(2024, 6, 1), attended=[self.other])
        for now, known, left in ((when(2024, 12, 31), False, 0), (when(2025, 1, 1), True, 1)):
            row = unit_rows(now)['years'][2023]
            # Twelve calendar months after Ann's last day she has not left yet; the day after, she has.
            self.assertEqual((row.left_known[12], row.flows[12]['left']), (known, left), now)

    def test_the_retention_charts_say_it_in_lines(self):
        self.members_coming_and_going()
        people, flows = self.tips('people', ''), self.tips('flows', '')
        self.assertEqual(people[-1].split(' | '),
                         ['2024 to 15 Jun: 2 active', '1 in their first year (joined 2024)', '1 joined 2020 or earlier'])
        self.assertEqual(people[3].split(' | '), ['2023: 1 active', '1 after 1 to 2 years (joined 2021)'])
        self.assertEqual(flows[2].split(' | '),
                         ['2022', '2 joined', '0 came back', '2 left', '0 left, came back later', '+0 net change'])
        # Who left in 2023 is known only once 2024 is over.
        self.assertEqual(flows[3].split(' | ')[-1], 'Net change not yet known')
        self.assertEqual([v['label'] for v in self.chart('flows')['views']], ['12 months', '24 months', '36 months'])
        chart = self.chart('people')
        # A band for each stretch of years since joining; whoever joined as the records start is kept apart.
        self.assertEqual([k['label'] for k in chart['views'][0]['panels'][0]['key']],
                         ['First year', '1 to 2 years', '3 to 5 years', '6 to 10 years', 'Over 10 years',
                          'Joined 2020 or earlier'])
        self.assertEqual(chart['measures'][0]['title'], 'Active members, by years since joining, 2020 to Present')
        self.assertFalse(chart['wide'])            # a tile, beside the joining and leaving chart

    def test_the_bands_of_years_since_joining_add_up_to_the_members_active(self):
        years = self.members_coming_and_going()
        self.assertEqual([sum(figures) for figures in self.figures('people', '')],
                         [sum(years[y].active.values()) for y in (2020, 2021, 2022, 2023, 2024)])

    def test_those_there_as_the_records_start_join_the_longest_band_once_all_have_over_ten_years(self):
        # Ann, there in 2013 as the records start, is kept apart through 2023 and is "over 10 years" in 2024.
        for day in (7, 14):
            self.make_event('training', when(2013, 2, day), attended=[self.member])
        for year in range(2013, 2025):
            self.make_event('training', when(year, 3, 7), attended=[self.member])
        panel = self.panel('people', '')
        band = {(k['colour'], k.get('ramp')): k['label'] for k in panel['key']}     # a part's band, as the key names it
        self.assertEqual([[band[(part['colour'], part.get('ramp'))] for part in cell['parts'] if part['sizes'][0]]
                          for cell in panel['cells'][-2:]],
                         [['Joined 2013 or earlier'], ['Over 10 years']])

    def test_a_team_sets_on_how_many_days_a_member_has_joined(self):
        # Records from 2020; a meeting in 2021, then one day at an operation in 2022.
        self.make_event('training', when(2020, 3, 7), attended=[self.other])
        self.make_event('meeting', when(2021, 3, 7), attended=[self.member])
        self.make_event('operation', when(2022, 3, 7), attended=[self.member])
        for joined_at, joined in ((2, 2021), (1, 2022)):            # their first event, or that day
            with override_settings(ACTIVITY_REPORTS={'JOINED_AT': joined_at}):
                self.assertEqual(self.years()[2022].active[joined], 1, joined_at)
        with override_settings(ACTIVITY_REPORTS={'JOINED_AT': 2}):
            self.assertTrue(dict(unit_activity(NOW)['glossary'])['Joined'].startswith(
                "A member's second day at an operation or a training not open to guests; with fewer than two, "))

    def test_a_team_sets_the_months_after_which_a_member_has_left(self):
        # Trainings in January and September 2023: eight months apart, and nine before today.
        for month in (1, 9):
            self.make_event('training', when(2023, month, 7), attended=[self.member])
        with override_settings(ACTIVITY_REPORTS={'LEFT_AFTER': (6, 18)}):
            row = self.years()[2023]
            self.assertEqual(row.flows, {6: {'joined': 0, 'came_back': 1, 'left': 1, 'left_returned': 1},
                                         18: {'joined': 0, 'came_back': 0, 'left': 0, 'left_returned': 0}})
            self.assertEqual(sum(row.active.values()), 1)             # active once, though in two stretches
            self.assertEqual([v['label'] for v in self.chart('flows')['views']], ['6 months', '18 months'])
            self.assertTrue(dict(unit_activity(NOW)['glossary'])['Left'].startswith(
                '6 months have passed without an operation, training or community event (18 where switched). '))
        # A setting of one is written in the singular.
        with override_settings(ACTIVITY_REPORTS={'LEFT_AFTER': (1, 18)}):
            view = self.chart('flows')['views'][0]
            self.assertEqual((view['label'], view['panels'][0]['name']),
                             ('1 month', 'Members joining and leaving, left after 1 month of no activity'))
            self.assertTrue(dict(unit_activity(NOW)['glossary'])['Left'].startswith(
                '1 month has passed without an operation, training or community event (18 where switched). '))

    def test_months_without_activity_are_calendar_months(self):
        # Records from 2022. One member out on 1 March 2023 and 1 March 2024: twelve months to the day, across
        # 29 February, so they never left; another out on 1 March 2023 and 2 March 2024, a day more, left.
        self.make_event('training', when(2022, 3, 7), attended=[self.third])
        for member, back in ((self.member, 1), (self.other, 2)):
            self.make_event('training', when(2023, 3, 1), attended=[member])
            self.make_event('training', when(2024, 3, back), attended=[member])
        with override_settings(ACTIVITY_REPORTS={'LEFT_AFTER': (12,)}):
            years = self.years()
            self.assertEqual((years[2023].flows[12]['left_returned'], years[2024].flows[12]['came_back']), (1, 1))

    def test_a_member_who_leaves_and_comes_back_twice(self):
        for year in (2016, 2019, 2022):          # three years apart each time
            for day in (7, 14, 21):
                self.make_event('training', when(year, 3, day), attended=[self.member])
        self.make_event('training', when(2015, 3, 7), attended=[self.other])        # the records start earlier
        years = self.years()
        self.assertEqual([(y, years[y].flows[12]['joined'], years[y].flows[12]['came_back'],
                           years[y].flows[12]['left_returned'], years[y].flows[12]['left'])
                          for y in (2016, 2019, 2022)],
                         [(2016, 1, 0, 1, 0), (2019, 0, 1, 1, 0), (2022, 0, 1, 0, 1)])
        self.assertEqual([sum(years[y].active.values()) for y in range(2016, 2023)], [1, 0, 0, 1, 0, 0, 1])

    def test_every_plot_has_a_name_of_its_own_for_a_screen_reader(self):
        self.members_coming_and_going()
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        names = []
        for chart in unit_activity(NOW)['charts']:
            chart = chart['menu']['options'][0]['chart'] if chart.get('menu') else chart
            names += [panel['name'] for view in chart['views'] for panel in view['panels']]
        self.assertEqual(len(names), len(set(names)), names)
        self.assertNotIn('By year', names)
        self.assertIn('Stretches in the field, by days in a row', names)
        self.assertIn('Operations, members and how many led', names)

    def test_no_two_charts_on_the_page_share_a_name(self):
        # A chart's name makes the ids its figure is labelled by and the names of its switches, so each
        # chart has one of its own: one figure for each title, and outside the menus' templates, one title.
        self.members_coming_and_going()
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(event, when(2024, 2, 7), 'Immediate callout: search', 'Available?', {self.member: 60})
        html = self.served_page()
        titles = re.findall(r'<figure class="chart" aria-labelledby="([^"]+)"', html)
        self.assertEqual(len(titles), len(set(titles)), titles)
        self.assertEqual(set(titles), {chart['name'] + '-title' for chart in unit_activity(NOW)['charts']})
        shown = re.sub(r'<template\b.*?</template>', '', html, flags=re.S)
        self.assertEqual([title for title in titles if shown.count('id="{}"'.format(title)) != 1], [])

    def test_the_sections_and_the_glossary_follow_the_page(self):
        self.members_coming_and_going()
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        activity = unit_activity(NOW)
        self.assertEqual([(section['title'], [c['name'] for c in section['charts']]) for section in activity['sections']],
                         [('Operations', ['operations', 'responders', 'runs', 'status']),
                          ('Participation', ['days', 'members']), ('Retention', ['people', 'flows'])])
        terms = [term for term, _ in activity['glossary']]
        order = [terms.index(t) for t in (
            'Responder', 'Operation day', 'Responder-day, responder-hours, operations attended', 'Status',
            'Callout page, callout to a member', 'Unit active hours', 'Unique member count', 'Joined', 'Active')]
        self.assertEqual(order, sorted(order))

    def test_an_entry_over_new_year_counts_each_day_in_its_own_year(self):
        # From noon on 31 December 2022 for 36 hours: a day in each year, on one event of 2022.
        self.make_event('operation', when(2022, 12, 31), attended=[self.member], hours=36)
        years = self.years()
        unit, people = ([years[y].participation[who] for y in (2022, 2023)] for who in ('unit', 'people'))
        self.assertEqual([sum(counted['days']['operation'].values()) for counted in unit], [1, 1])
        self.assertEqual([sum(counted['events']['operation'].values()) for counted in unit], [1, 0])
        self.assertEqual([sum(years[y].operations.values()) for y in (2022, 2023)], [1, 0])
        self.assertEqual([round(sum(counted['hours']['operation'].values())) for counted in people], [12, 24])
        self.assertEqual(years[2022].runs['two'], 1)

    def test_hours_in_the_figures_are_to_one_decimal_as_on_a_members_report(self):
        # An hour on a Wednesday in 2023, and half an hour on one in 2024: the half hour is not 0, and an
        # hour is still "hours", as a figure to one decimal reads.
        self.make_event('operation', when(2023, 2, 8), attended=[self.member], hours=1)
        self.make_event('operation', when(2024, 2, 7), attended=[self.member], hours=0.5)
        self.assertEqual(self.tips('days', 'Operations', measure='Hours'),
                         ['2023: 1.0 hours | 1.0 on weekdays | 0.0 on weekends',
                          '2024 to 15 Jun: 0.5 hours | 0.5 on weekdays | 0.0 on weekends'])
        self.assertEqual(self.tips('days', 'Operations', measure='Hours', view=1)[1],
                         '2024 to 15 Jun: 0.5 member-hours | 0.5 on weekdays | 0.0 on weekends')
        self.assertEqual(self.tips('status', '', measure='Hours')[-1],
                         '2024 to 15 Jun: 0.5 responder-hours | 0.0 Trainee | 0.5 Field Member '
                         '| 0.0 Technical Member | 0.0 Other status')

    def test_which_trainings_are_open_to_guests(self):
        # The default, read ignoring case, as patterns are.
        guest_friendly = re.compile(report_settings().GUEST_FRIENDLY_TITLE, re.IGNORECASE)
        for title in ('SAR Basic', 'sar basic 2', 'SAR-Basic', 'Map and compass *G', 'Steep ground * G - rigging',
                      'Sign cutting G*', 'Ice axe drill *g', 'Map reading (g)', 'Mock rescue G',
                      'Guest mock rescue', 'First aid (Guest Friendly)', 'Ridge guest hike', 'Open to guests',
                      'Volcano guest hike', 'Open for guests', 'For guests: map reading'):
            self.assertTrue(guest_friendly.search(title), title)
        for title in ('Map and compass *', 'Low Angle', 'Glacier travel', 'Rigging', 'Dog team night', 'Guesthouse rescue',
                      'Sat comms', 'Cartography guest lecturer', 'Guest-lecturer night', 'Guest speaker: avalanche',
                      'Medical guest lecture', 'Rope rescue with guest instructor', 'Avalanche talk, guest presenter',
                      'Helicopter ops (no guests)', 'Members only, no guests', 'no  guests (members only)',
                      'No-guests drill', 'NO GUESTS', 'Not for guests', 'Rigging, not  for guests',
                      'Not-for-guests drill', '4G/LTE comms', 'Comms over 4G', 'Type G litter rigging',
                      'G.P.S. map reading', 'Plan G drill'):
            self.assertFalse(guest_friendly.search(title), title)

    def test_a_team_sets_which_trainings_are_open_to_guests(self):
        for day, title in ((7, 'SAR Basic'), (8, 'Open day drill')):
            event = self.make_event('training', when(2024, 2, day), attended=[self.member])
            Event.objects.filter(id=event.id).update(title=title)
        with override_settings(ACTIVITY_REPORTS={'GUEST_FRIENDLY_TITLE': r'open\s+day'}):
            self.assertEqual([entry.members_only for entry in unit_entries(NOW)], [True, False])

    def test_which_pages_start_an_immediate_callout(self):
        # The default, read ignoring case, as patterns are, from the start of a page's text.
        starts_immediate = re.compile(report_settings().IMMEDIATE_CALLOUT, re.IGNORECASE)
        for text in ('Immediate callout: search', 'IMMEDIATE Callout', 'Repage: Immediate callout: search',
                     'Repage: Repage: Immediate callout', 'Re: immediate callout', 'Repage 2: Immediate callout',
                     'UPDATE: Immediate callout', 'Fwd: Immediate callout', 'FW: Re: immediate callout',
                     'UPDATE #1: IMMEDIATE', 'Repage #2: Immediate callout',
                     # As the page form begins a page, and as a repage of it begins.
                     'Ridge search OP1: Immediate callout', 'Repage: Ridge search OP2: Immediate callout'):
            self.assertTrue(starts_immediate.match(text), text)
        for text in ('CANCELLED - immediate callout for overdue biker', 'Heads Up: may become immediate',
                     'Delayed callout, not immediate', 'Immediately cancel the search', 'Cancel immediate callout',
                     'Ridge search OP1: may become immediate'):
            self.assertFalse(starts_immediate.match(text), text)

    def test_a_page_of_many_words_put_before_is_read_at_once(self):
        # Words put before that a page then does not follow with "immediate": each read once, not tried in
        # every way the spaces between them could be split.
        starts_immediate = re.compile(report_settings().IMMEDIATE_CALLOUT, re.IGNORECASE)
        for crafted in ('Repage  ' * 30 + 'x', 'Repage #2 ' * 30 + 'x', 'Fwd: ' * 30 + 'Ridge search OP1: x'):
            start = time.perf_counter()
            self.assertFalse(starts_immediate.match(crafted))
            self.assertLess(time.perf_counter() - start, 0.5, crafted[:20])

    def test_a_team_sets_which_pages_start_an_immediate_callout_and_how_the_glossary_says_so(self):
        for month, text in ((1, 'URGENT: search'), (2, 'Immediate callout: search')):
            event = self.make_event('operation', when(2024, month, 7) + timedelta(minutes=20), attended=[self.member])
            self.page(event, when(2024, month, 7), text, 'Available?', {self.member: 60})
        with override_settings(ACTIVITY_REPORTS={'IMMEDIATE_CALLOUT': r'urgent\b',
                                                 'IMMEDIATE_CALLOUT_SAID': 'starting "Urgent"'}):
            self.assertEqual(self.years()[2024].first_out, {'half': 1, 'hour': 0, 'later': 0, 'none': 0})
            self.assertTrue(dict(unit_activity(NOW)['glossary'])['Immediate callout'].startswith(
                'An operation with a callout page starting "Urgent". Timed from'))

    def test_the_report_asks_the_database_a_fixed_number_of_questions(self):
        # The same questions however many events and members there are: one query for all of each.
        for month in (1, 2, 3, 4):
            event = self.make_event('operation', when(2024, month, 7), attended=[self.member, self.other])
            self.page(event, when(2024, month, 7), 'Immediate callout', 'Available?', {self.member: 60})
        self.make_event('operation', when(2024, 5, 7), no_time=[self.member])       # did not run
        # Which operations ran is read from the entries already read, not asked again; one question asks
        # which of those that did not run were only heads-ups, one when members left home on immediate
        # callouts, from entries whether or not their times are complete, and one where the unit's records
        # start (counting.records_from).
        with self.assertNumQueries(11):
            unit_rows(NOW)

    def test_days_after_today_do_not_count_yet(self):
        # An operation that began yesterday, with four days logged: only yesterday and today count.
        self.make_event('operation', when(2024, 6, 14), attended=[self.member], hours=96)
        row = self.years()[2024]
        self.assertEqual(sum(row.participation['unit']['days']['operation'].values()), 2)
        self.assertEqual(sum(row.participation['people']['days']['operation'].values()), 2)
        self.assertEqual(sum(row.operation_days.values()), 2)
        self.assertEqual(row.runs, {'day': 0, 'long_day': 0, 'two': 1, 'more': 0})
        self.assertLessEqual(sum(row.participation['unit']['hours']['operation'].values()), 36)
        self.assertLessEqual(sum(row.participation['people']['hours']['operation'].values()), 48)

    def test_time_after_today_does_not_make_a_long_day(self):
        # Out from noon today to 4am tomorrow: up to the end of today that is 12 hours, not over 12.
        event = self.make_event('operation', self.local(2024, 6, 15, 12))
        Participant.objects.create(period=event.period_set.first(), member=self.member,
                                   en_route_at=self.local(2024, 6, 15, 12), return_home_at=self.local(2024, 6, 16, 4))
        row = self.years()[2024]
        self.assertEqual(row.runs, {'day': 1, 'long_day': 0, 'two': 0, 'more': 0})
        self.assertEqual(sum(row.participation['unit']['hours']['operation'].values()), 12)

    def test_one_stray_early_record_does_not_move_where_the_records_start(self):
        # A meeting entered for 2005; the records proper start in 2020.
        self.make_event('meeting', when(2005, 3, 1), attended=[self.other])
        for day in (7, 14, 21):
            self.make_event('training', when(2020, 3, day), attended=[self.member])
        self.make_event('training', when(2022, 3, 7), attended=[self.member])
        self.make_event('training', when(2024, 3, 7), attended=[self.member, self.other])
        counted = unit_rows(NOW)
        self.assertEqual(counted['records_from'], 2020)
        # Ann, there as the records start, counts as already there rather than joining; the grey band is 2020's.
        self.assertEqual(counted['years'][2020].flows[12]['joined'], 0)
        self.assertEqual(self.chart('people')['views'][0]['panels'][0]['key'][-1]['label'], 'Joined 2020 or earlier')
        self.assertEqual(self.chart('people')['measures'][0]['title'],
                         'Active members, by years since joining, 2020 to Present')

    def test_joining_counts_days_not_entries(self):
        # A meeting in 2022, then a three-day operation in 2023: its third day is the day of joining,
        # though it is one entry.
        self.make_event('meeting', when(2022, 11, 8), attended=[self.member])
        self.make_event('operation', when(2023, 1, 6), attended=[self.member], hours=60)
        years = self.years()
        self.assertEqual(sum(years[2022].active.values()), 0)
        self.assertEqual(years[2023].active[2023], 1)

    def test_members_who_have_left_count_and_guests_do_not(self):
        alum, no_contact = self.make_member('Dee', 'MA'), self.make_member('Eve', 'MN')
        guest, guest_alum = self.make_member('Fay', 'G'), self.make_member('Gus', 'GA')
        self.make_event('operation', when(2023, 2, 7), attended=[alum, guest], ol=[no_contact])
        guests_alone = self.make_event('operation', when(2023, 3, 7), attended=[guest, guest_alum])
        self.page(guests_alone, when(2023, 3, 7), 'Callout', 'Available?', {})
        self.make_event('training', when(2023, 4, 8), attended=[guest])
        row = self.years()[2023]
        self.assertEqual(row.members['operation'], {'others': 1, 'led': 1})
        self.assertEqual(row.operations, {'thin': 1, 'middling': 0, 'full': 0, 'called_off': 1, 'heads_up': 0})
        self.assertEqual(row.participation['people']['hours']['operation'], {'weekday': 8, 'weekend': 0})
        self.assertEqual(row.participation['unit']['days']['training'], {'weekday': 0, 'weekend': 0})
        self.assertEqual(unit_rows(NOW)['responded'], [(date(2023, 2, 7), 2)])

    def test_each_chart_band_is_a_category_the_report_counts(self):
        # The charts draw a band for each category the counting splits a count by, in its order. Every set
        # of bands is defined once, at the top of the module, or built there from a team's rules, and listed here.
        from main.lib import unit_activity as drawn, unit_counting as counted
        built = [drawn.size_bands(), drawn.reply_bands(), drawn.departure_bands(), drawn.run_bands(),
                 drawn.status_bands()]
        counted_in = [(drawn.WEEK, counted.PARTS_OF_WEEK.names), (built[0], counted.SIZES),
                      (drawn.DID_NOT_RUN, counted.NOT_RUN),
                      (built[4], report_settings().BANDED_STATUSES + (counted.OTHER_STATUS,)),
                      (built[3], counted.RUN_LENGTHS), (built[1], counted.REPLY_KINDS),
                      (built[2], counted.DEPARTURE_KINDS), (drawn.FLOWS, counted.FLOW_KINDS),
                      (drawn.TENURE, drawn.YEARS_SINCE_JOINING.names)]
        counted_in += [(drawn.MEMBERS[t], counted.ROLES) for t in TYPES]
        for bands, names in counted_in:
            self.assertEqual(tuple(band.name for band in bands), tuple(names))
        defined = [v for v in vars(drawn).values() if isinstance(v, drawn.Bands)] + list(drawn.MEMBERS.values()) + built
        self.assertEqual(sorted(map(id, defined)), sorted(id(bands) for bands, _ in counted_in))
        # Every band defined on its own is in one of those sets. Those of no counted category are built: they
        # split what is read from operation times at OPERATION_TIMES_FROM (early_band and from_times_band).
        in_sets = {band for bands, _ in counted_in for band in bands}
        self.assertEqual({v for v in vars(drawn).values() if isinstance(v, drawn.Band)} - in_sets, set())
        self.assertLess(set(drawn.DEPARTURES), set(counted.FLOW_KINDS))
        self.assertEqual(tuple(drawn.WHO), counted.WHOSE)
        self.assertEqual(tuple(drawn.COUNTED), counted.MEASURES)

    def test_first_year(self):
        # The page's first year: an empty year or two keeps what came before; a longer gap marks a stray record.
        self.assertEqual(first_year({1983, 2021, 2022, 2024}), 2021)
        self.assertEqual(first_year({2019, 2022, 2024}), 2019)
        self.assertEqual(first_year({2018, 2022, 2024}), 2022)
        self.assertEqual(first_year({2024}), 2024)

    def test_a_team_sets_how_many_empty_years_mark_a_stray_record(self):
        # Three empty years after 2016, then one after 2020.
        for stray_before, first in ((1, 2022), (2, 2020), (4, 2016)):
            with override_settings(ACTIVITY_REPORTS={'STRAY_BEFORE': stray_before}):
                self.assertEqual(first_year({2016, 2020, 2022}), first, stray_before)

    def test_a_stray_record_does_not_size_the_responders_chart(self):
        # Four out on a stray operation in 1995; two at most since 2022. The columns run to 2 responders.
        self.make_event('operation', when(1995, 2, 7), attended=[self.member, self.other, self.third,
                                                                 self.make_member('Dee', 'T')])
        for year in (2022, 2024):
            self.make_event('operation', when(year, 2, 7), attended=[self.member, self.other])
        self.assertEqual(len(self.drawn('responders', '')), 2)

    def test_the_records_of_joining_start_with_the_page(self):
        # Trainings in 2015, then 2020 and 2021, with meetings between: the page starts in 2015, and so
        # do the records of joining, though no operation, training or community event filled the gap.
        self.make_event('training', when(2015, 3, 7), attended=[self.member])
        for year in (2016, 2017, 2018, 2019):
            self.make_event('meeting', when(year, 3, 7), attended=[self.member])
        for year in (2020, 2021):
            self.make_event('training', when(year, 3, 7), attended=[self.other])
        self.assertEqual(unit_activity(NOW)['period'][:4], '2015')
        self.assertEqual(unit_rows(NOW)['records_from'], 2015)

    def test_a_year_without_any_does_not_hide_the_years_before(self):
        # Operations in 2020 to 2022 and none since: the chart still shows them, with empty years after.
        for year in (2020, 2021, 2022):
            self.make_event('operation', when(year, 2, 7), attended=[self.member])
        self.assertEqual(len(self.drawn('operations', '')), 5)
        self.assertEqual(self.chart('operations')['measures'][0]['title'],
                         'Operations, by unique responder count, 2020 to Present')
        self.assertEqual(unit_activity(NOW)['period'], '2020 to 15 Jun 2024')

    def test_a_chart_keeps_a_record_before_a_long_gap_after_the_pages_first_year(self):
        # Operations every year from 2010, so the page starts then; immediate callouts in 2015, none from
        # 2016 to 2018, then 2019 on. The stray rule is the page's alone: 2015 shows, the empty years with it.
        for year in range(2010, 2025):
            self.make_event('operation', when(year, 2, 7), attended=[self.member])
        for year in (2015, 2019, 2020, 2021, 2022, 2023, 2024):
            event = self.make_event('operation', when(year, 5, 7) + timedelta(minutes=20), attended=[self.member])
            self.page(event, when(year, 5, 7), 'Immediate callout', 'Available?', {self.member: 60})
        self.assertEqual(unit_activity(NOW)['period'], '2010 to 15 Jun 2024')
        self.assertEqual(self.chart('immediate')['measures'][0]['title'],
                         'Immediate callouts, by time to first departure, 2015 to Present')
        years = self.years()
        self.assertEqual((len(self.drawn('immediate', '')), sum(years[2015].first_out.values()),
                          sum(years[2016].first_out.values())), (10, 1, 0))
        # The charts with a year menu too.
        for name in ('calls', 'reply_hours'):
            chart = self.chart(name)
            self.assertEqual([o['label'] for o in chart['menu']['options']],
                             ['All years', '2024', '2023', '2022', '2021', '2020', '2019', '2015'], name)
            self.assertTrue(chart['measures'][0]['title'].endswith(', 2015 to Present'), name)

    def test_charts_start_where_their_data_does_and_run_to_the_present(self):
        self.make_event('operation', when(2018, 2, 7), no_time=[self.member])     # a stray early record
        self.make_event('operation', when(2022, 2, 7), no_time=[self.member])
        self.make_event('operation', when(2023, 2, 7), attended=[self.member])
        self.make_event('training', when(2023, 3, 4), attended=[self.member])
        self.make_event('training', when(2024, 3, 4), attended=[self.member])
        days, operations = self.chart('days'), self.chart('operations')
        self.assertCountEqual([t['text'] for t in days['titles']],
                         ['Unit active days (any member out), by type and part of the week, 2023 to Present',
                          "Member-days (each member's days, added up), by type and part of the week, 2023 to Present",
                          'Unit events (any member out), by type and part of the week, 2023 to Present',
                          "Events attended (each member's events, added up), by type and part of the week, "
                          '2023 to Present',
                          'Unit active hours (any member out), by type and part of the week, 2023 to Present',
                          "Member-hours (each member's hours, added up), by type and part of the week, "
                          '2023 to Present'])
        self.assertIn('2022 to Present', operations['measures'][0]['title'])
        activity = unit_activity(NOW)
        self.assertEqual(activity['period'], '2022 to 15 Jun 2024')
        self.assertEqual({c['name']: c['wide'] for c in activity['charts'] if c['name'] in ('days', 'operations')},
                         {'days': True, 'operations': False})
        self.assertEqual(len(self.panel('operations', '')['cells']), 3)

    def test_operations_before_times_were_logged(self):
        for year in range(2012, 2025):
            self.make_event('operation', when(year, 2, 7), no_time=[self.member])
        panel = self.panel('operations', '')
        self.assertEqual(panel['cells'][0]['tips'][0],
                         {'head': '2012: 1 operation', 'lines': [{'text': 'Few with times logged'}]})
        self.assertEqual(panel['cells'][0]['parts'][0]['colour'], 'muted')
        self.assertEqual(panel['key'][-1]['label'], 'Before 2013')

    def test_what_is_read_from_operation_times_is_grey_before_they_were_logged(self):
        self.make_event('operation', when(2012, 2, 7), attended=[self.member])
        self.make_event('operation', when(2014, 2, 7), attended=[self.member], ol=[self.other])
        self.make_event('training', when(2012, 3, 7), attended=[self.member])
        before, since = 'Few operations with times logged', 'Before 2013'

        def grey(cell):
            return [part['colour'] for part in cell['parts'] if part['sizes'][0]] == ['muted']

        # The operations chart's days, as its operations.
        days = self.panel('operations', '')['cells']
        self.assertTrue(grey(days[0]) and not grey(days[2]))
        self.assertEqual(self.tips('operations', '', measure='Days')[0], '2012: 1 day | ' + before)
        # Operations at each responder count: the early part grey over all years, all of it in 2012.
        responders = self.panel('responders', '')
        self.assertEqual(responders['cells'][0]['tips'][0]['lines'][:2],
                         [{'number': 0, 'label': 'from 2013'},
                          {'number': 1, 'label': 'before 2013, few operations with times logged'}])
        self.assertEqual(responders['key'][-1]['label'], since)
        self.assertEqual(self.tips('responders', '', option='2012')[0],
                         '1 responder: 1 operation | {} | in 2012'.format(before))
        self.assertTrue(grey(self.panel('responders', '', option='2012')['cells'][0]))
        # A year's key names only what it draws: before 2013 only the grey, from 2013 only the blue.
        self.assertEqual([[k['label'] for k in self.panel('responders', '', view, option)['key']]
                          for view in (0, 1) for option in ('2012', '2014')],
                         [[since], ['Operations'], [since], ['Operation days']])
        self.assertEqual(self.drawn('responders', '', option='2014'), [False, True])
        self.assertFalse(grey(self.panel('responders', '', option='2014')['cells'][1]))
        # Stretches, and members at operations; members at trainings are as they were.
        for name, label in (('runs', ''), ('members', 'Operations')):
            cells = self.panel(name, label)['cells']
            self.assertTrue(grey(cells[0]) and not grey(cells[2]), name)
            self.assertEqual(self.tips(name, label)[0].split(' | ')[1:], [before], name)
            self.assertEqual(self.panel(name, label)['key'][-1]['label'], since, name)
        self.assertFalse(grey(self.panel('members', 'Trainings')['cells'][0]))
        self.assertNotIn(since, [k['label'] for k in self.panel('members', 'Trainings')['key']])

        def colours(cell):
            """The colours drawn in a column, on any of its measures."""
            return {part['colour'] for part in cell['parts'] if any(part['sizes'])}

        # The days chart's operations, for the unit and for its members, on every measure; its trainings are as
        # they were.
        measures = ('Days', 'Events', 'Hours')
        for view, heads in ((0, ['2012: 1 day', '2012: 1 event', '2012: 4.0 hours']),
                            (1, ['2012: 1 member-day', '2012: 1 event attended', '2012: 4.0 member-hours'])):
            cells = self.panel('days', 'Operations', view)['cells']
            self.assertEqual((colours(cells[0]), colours(cells[2])), ({'muted'}, {'1-light'}), view)
            self.assertEqual([self.tips('days', 'Operations', measure, view)[0] for measure in measures],
                             [head + ' | ' + before for head in heads])
            self.assertEqual(self.panel('days', 'Operations', view)['key'][-1]['label'], since)
            self.assertEqual(colours(self.panel('days', 'Trainings', view)['cells'][0]), {'1-light'})
            self.assertNotIn(since, [k['label'] for k in self.panel('days', 'Trainings', view)['key']])
        # The status chart, on every measure: its grey is the lighter one, as Other status takes the darker.
        cells = self.panel('status', '')['cells']
        self.assertEqual((colours(cells[0]), colours(cells[2])), ({'muted-light'}, {'1'}))
        self.assertEqual([self.tips('status', '', measure)[0] for measure in measures],
                         ['2012: 1 responder-day | ' + before, '2012: 1 operation attended in the field | ' + before,
                          '2012: 4.0 responder-hours | ' + before])
        self.assertEqual([(k['colour'], k['label']) for k in self.panel('status', '')['key']][-2:],
                         [('muted', 'Other status'), ('muted-light', since)])

    def test_a_team_sets_the_year_from_which_operation_times_were_logged(self):
        for year in (2019, 2021):
            self.make_event('operation', when(year, 2, 7), attended=[self.member])
        with override_settings(ACTIVITY_REPORTS={'OPERATION_TIMES_FROM': 2020}):
            cells = self.panel('operations', '')['cells']
            self.assertEqual([[part['colour'] for part in cell['parts'] if part['sizes'][0]] for cell in cells[:3]],
                             [['muted'], [], ['1-light']])               # 2019 grey; 2020 empty; 2021 by size
            self.assertEqual(self.panel('operations', '')['key'][-1]['label'], 'Before 2020')
            self.assertIn(('Before 2020', 'Few operations had their times logged.'), unit_activity(NOW)['glossary'])

    def test_the_activity_reports_paths_are_theirs_and_not_activity_types(self):
        from django.urls import resolve
        from main.views import ReportEventMemberView, ReportUnitActivityView
        self.assertIs(resolve('/reports/activity-unit/').func.view_class, ReportUnitActivityView)
        self.assertIs(resolve('/reports/activity-member/1/').func.view_class, ReportEventMemberView)

    # The rules at their edges. In winter California is 8 hours behind UTC, so 8pm on 31 December is
    # already 1 January in UTC: these tests tell local days and years from UTC ones.

    def local(self, year, month, day, hour, minute=0):
        """A time on the local clock, in California."""
        return timezone.make_aware(datetime(year, month, day, hour, minute))

    def test_the_responders_menu_takes_in_operation_days_before_any_operation_started(self):
        # An operation from just after midnight on New Year's Day 2016, its responder out from 30 December.
        event = self.make_event('operation', self.local(2016, 1, 1, 0, 30), no_time=[self.member])
        Participant.objects.filter(period=event.period_set.first()).update(
            en_route_at=self.local(2015, 12, 30, 12), return_home_at=self.local(2016, 1, 2, 12))
        # With the records starting in 2016, the days before them count nowhere (counting.records_from).
        self.assertEqual([o['label'] for o in self.chart('responders')['menu']['options']], ['All years', '2016'])
        # With a training in 2015 they start then, and the menu takes in the days out in 2015.
        self.make_event('training', when(2015, 3, 7), attended=[self.other])
        chart = self.chart('responders')
        self.assertEqual([o['label'] for o in chart['menu']['options']], ['All years', '2016', '2015'])
        self.assertEqual(self.drawn('responders', '', view=1, option='2015'), [True])      # its two days in 2015

    def test_an_entry_flagged_both_ahc_and_ol_is_the_ahc_and_does_not_lead(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        Participant.objects.create(period=event.period_set.first(), member=self.other, ahc=True, ol=True,
                                   en_route_at=when(2024, 2, 7), return_home_at=when(2024, 2, 7) + timedelta(hours=2))
        row = self.years()[2024]
        self.assertEqual(row.members['operation'], {'led': 0, 'others': 2})
        self.assertEqual(row.without_ol, 1)

    def test_meetings_do_not_keep_a_member_active(self):
        self.make_event('operation', when(2020, 2, 7), attended=[self.member])
        for year in (2021, 2022):
            self.make_event('meeting', when(year, 2, 7), attended=[self.member])
        years = self.years()
        self.assertEqual([sum(years[y].active.values()) for y in (2020, 2021, 2022)], [1, 0, 0])

    def test_a_member_first_recorded_after_a_day_counts_under_their_first_recorded_status(self):
        self.make_event('operation', when(2024, 2, 7), attended=[self.member, self.third])
        history = Member.history.model.objects
        history.filter(id=self.third.id).delete()
        for status, month in (('FM', 5), ('TM', 6)):        # first recorded in May, then made TM in June
            self.third.status = status
            self.third.save()
            history.filter(id=self.third.id, status=status).update(history_date=when(2024, month, 1))
        self.assertEqual(self.years()[2024].status_days, {'T': 0, 'FM': 2, 'TM': 0, 'other': 0})

    def test_an_operation_belongs_to_the_local_year_it_started(self):
        self.make_event('operation', self.local(2023, 12, 31, 20), attended=[self.member], hours=2)
        years = self.years()
        self.assertEqual((years[2023].operations['thin'], years[2024].operations['thin']), (1, 0))

    def test_a_status_change_counts_from_its_local_day(self):
        self.make_event('operation', self.local(2024, 1, 31, 12), attended=[self.third], hours=4)
        self.third.status = 'FM'
        self.third.save()
        # A Field Member from 9pm on 31 January, local time: 1 February in UTC.
        Member.history.filter(id=self.third.id, status='FM').update(history_date=self.local(2024, 1, 31, 21))
        self.assertEqual(self.years()[2024].status_days, {'T': 0, 'FM': 1, 'TM': 0, 'other': 0})

    def test_an_event_attended_on_two_periods_is_one_event_attended(self):
        event = self.make_event('training', when(2024, 2, 7), attended=[self.member], hours=3)
        Participant.objects.create(period=Period.objects.create(event=event, position=2), member=self.member,
                                   en_route_at=when(2024, 2, 8), return_home_at=when(2024, 2, 8) + timedelta(hours=3))
        self.assertEqual(self.years()[2024].participation['people']['events']['training'], {'weekday': 1, 'weekend': 0})

    def test_a_unit_event_counts_in_the_year_it_started_whatever_day_was_attended(self):
        # From noon on 31 December 2023; the only time logged is on New Year's Day.
        event = self.make_event('training', self.local(2023, 12, 31, 12), hours=48)
        Participant.objects.create(period=event.period_set.first(), member=self.member,
                                   en_route_at=self.local(2024, 1, 1, 9), return_home_at=self.local(2024, 1, 1, 13))
        years = self.years()
        events = {y: years[y].participation['unit']['events']['training'] for y in (2023, 2024)}
        self.assertEqual(events, {2023: {'weekday': 0, 'weekend': 1}, 2024: {'weekday': 0, 'weekend': 0}})   # a Sunday
        # The days chart and the page's period start in 2023, for the event.
        self.assertIn('Unit events (any member out), by type and part of the week, 2023 to Present',
                      [title['text'] for title in self.chart('days')['titles']])
        self.assertTrue(unit_activity(NOW)['period'].startswith('2023 to '))

    def test_a_member_whose_first_day_is_a_stray_record_counts_as_joining_when_the_records_start(self):
        # A training in 2005, far before the rest, then community events: fewer than three member-only
        # days, so Ann joined on her first day, in 2005; the records start in 2020.
        self.make_event('training', when(2005, 3, 7), attended=[self.member])
        for year in (2020, 2021):
            self.make_event('community', when(year, 3, 7), attended=[self.member])
        years = self.years()
        self.assertEqual(years[2020].active[2020], 1)
        self.assertEqual(sum(years[2021].active.values()), 1)

    def test_an_entry_over_two_years_has_its_member_attending_in_each(self):
        self.make_event('operation', self.local(2023, 12, 31, 12), attended=[self.member], hours=24)
        years = self.years()
        self.assertEqual([years[y].members['operation'] for y in (2023, 2024)], [{'led': 0, 'others': 1}] * 2)

    def test_an_immediate_callout_belongs_to_the_year_its_operation_started(self):
        event = self.make_event('operation', self.local(2023, 12, 31, 22), attended=[self.member], hours=4)
        self.page(event, self.local(2024, 1, 1, 0, 30), 'Immediate callout: search', 'Available?', {self.member: 60})
        years = self.years()
        self.assertEqual([sum(years[y].first_out.values()) for y in (2023, 2024)], [1, 0])

    def test_twelve_hours_on_one_day_is_not_a_long_day(self):
        self.make_event('operation', self.local(2024, 2, 7, 8), attended=[self.member], hours=12)
        self.assertEqual(self.years()[2024].runs, {'day': 1, 'long_day': 0, 'two': 0, 'more': 0})

    def test_a_responder_leaving_as_the_page_is_sent_left_in_answer_to_it(self):
        event = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(event, when(2024, 2, 7), 'Immediate callout: search', 'Available?', {self.member: 60})
        self.assertEqual(self.years()[2024].first_out, {'half': 1, 'hour': 0, 'later': 0, 'none': 0})

    def test_a_page_for_an_operation_not_yet_started_is_not_a_first_page(self):
        started = self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.page(started, when(2024, 2, 7), 'Callout', 'Available?', {self.member: 60})
        coming = self.make_event('operation', NOW + timedelta(days=2), no_time=[self.member])
        self.page(coming, NOW - timedelta(hours=1), 'Heads up: tomorrow', 'Heads Up', {self.member: 60})
        self.assertEqual(len(unit_rows(NOW)['first_pages']), 1)

    def test_an_operation_finishing_this_moment_with_no_time_logged_was_called_off(self):
        called_off = self.make_event('operation', NOW - timedelta(hours=4), no_time=[self.member])
        self.page(called_off, NOW - timedelta(hours=5), 'Callout', 'Available?', {})
        self.assertEqual(self.years()[2024].operations['called_off'], 1)

    def test_2013_is_the_first_year_with_times_logged_and_not_grey(self):
        for year in (2012, 2013):
            self.make_event('operation', when(year, 2, 7), attended=[self.member])
        cells = self.panel('operations', '')['cells']
        self.assertEqual([[part['colour'] for part in cell['parts'] if part['sizes'][1]] for cell in cells[:2]],
                         [['muted'], ['1-light']])
        responders = self.panel('responders', '')['cells'][0]
        self.assertEqual(responders['tips'][0]['lines'][:2], [{'number': 1, 'label': 'from 2013'},
                                                              {'number': 1, 'label': early_band().said}])

    def test_the_days_and_status_charts_start_on_hours(self):
        # Each starts on Hours, its title the hours one, and its switch still reads Days, Events, Hours.
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        for name, title in (('days', 'Unit active hours (any member out), by type and part of the week, 2024'),
                            ('status', 'Responder-hours, by status on the day, 2024')):
            chart = self.chart(name)
            self.assertEqual(chart['titles'][0]['text'], title)
            self.assertEqual([(m['label'], m['number']) for m in chart['measures']],
                             [('Days', 2), ('Events', 3), ('Hours', 1)])
        # The others start on their first measure.
        self.assertEqual(self.chart('operations')['titles'][0]['text'],
                         'Operations, by unique responder count, 2024')
        # As drawn, before any script: Hours is the option on.
        html = self.served_page()
        for name in ('days', 'status'):
            self.assertIn('<input type="radio" name="{}-measure" checked><span>Hours</span>'.format(name), html)

    def test_page(self):
        self.paging_began()
        self.make_event('operation', when(2024, 2, 7), attended=[self.member])
        self.member.set_password('password')
        self.member.save()
        client = Client()
        url = reverse('report_activity_unit')
        self.assertEqual(client.get(url).status_code, 302)
        client.login(username=self.member.username, password='password')
        # The page reads the clock: it is set, so that the charts hold this test's data.
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            response = client.get(url)
            zipped = client.get(url, HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response.context['activity']['period'], '2024 to 15 Jun 2024')
        self.assertContains(response, '2024 to 15 Jun: 1 operation')
        self.assertEqual(zipped['Content-Encoding'], 'gzip')
        self.assertContains(response, '<!DOCTYPE html>\n<html lang="en">')
        self.assertContains(response, '<title>Unit Activity</title>')
        self.assertLess(len(zipped.content), len(response.content) / 5)
        self.assertContains(response, 'Unit active days (any member out), by type')
        self.assertContains(response, 'Member-days (each member&#x27;s days, added up), by type')
        self.assertContains(response, 'Unit Activity - ')
        self.assertContains(response, 'Operations, by unique responder count')
        self.assertContains(response, 'Unique member count at each type of event, and how many led')
        # One glossary at the foot: the terms both activity reports share, then this report's own.
        self.assertContains(response, '<caption>Glossary</caption>')
        self.assertContains(response, '<th scope="row">Day attended</th>')
        self.assertContains(response, '<th scope="row">Called off</th><td>The operation has finished with no member '
                                      'other than the AHC having a day attended on it up to today, and was called out '
                                      'with an availability page. Before 13 Feb 2019, when pages first said which '
                                      'they were, every operation that did not run counts here, pages or not, unless '
                                      'its title calls it a heads-up or it was never used (Events left out).</td>')
        self.assertContains(response, '<th scope="row">Heads-up only</th><td>The operation has finished with no member '
                                      'other than the AHC having a day attended on it up to today, and no availability '
                                      'page was sent: only heads-ups, or no page at all. Before 13 Feb 2019, it counts '
                                      'here if its title calls it a heads-up.</td>')
        # Every control says what it sets.
        self.assertEqual([(c['name'], c['measure_switch_label'], c['view_switch_label'])
                          for c in response.context['activity']['charts'] if c['name'] in ('days', 'flows')],
                         [('days', 'Count', 'For'), ('flows', 'Show', 'Left after no activity for')])
        self.assertContains(response, 'js/charts.js')
        # Only charts of more than one panel have the scale switch.
        self.assertEqual([c['name'] for c in response.context['activity']['charts'] if c['scale_switch']],
                         ['days', 'members'])
        self.assertContains(client.get(reverse('reports_list')), url)
