"""The activity reports' settings (main.lib.report_settings): the defaults, a team's keys over them, and the
values refused at start-up."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from main.lib.activity import glossary
from main.lib.counting import day_hours, reported_events
from main.lib.report_settings import ReportSettings, check_report_settings, report_settings
from main.models import Event, Message, RsvpTemplate
from main.tests.helpers import ActivityTestCase, when


class ReportSettingsTestCase(SimpleTestCase):
    def test_a_team_sets_only_the_keys_it_changes(self):
        self.assertEqual(report_settings(), ReportSettings())
        with override_settings(ACTIVITY_REPORTS={'DAY_HOURS': 3, 'CALLOUT_TEMPLATE': 'Can you go?'}):
            read = report_settings()
            self.assertEqual((read.DAY_HOURS, read.CALLOUT_TEMPLATE), (3, 'Can you go?'))
            self.assertEqual(read.SINGLE_DAY_HOURS, ReportSettings().SINGLE_DAY_HOURS)
        # And back to the defaults once the setting is.
        self.assertEqual(report_settings(), ReportSettings())

    def test_a_wrong_value_is_refused_at_start_up_naming_its_key(self):
        wrong = {
            'has no key': {'DAY_HOUR': 2},
            "'DAY_HOURS'] is a float": {'DAY_HOURS': '2'},
            "'MAX_ENTRY_DAYS'] is a int": {'MAX_ENTRY_DAYS': 7.5},
            "'MAX_ENTRY_DAYS'] is a int, not True": {'MAX_ENTRY_DAYS': True},
            "'TEST_TITLE'] is not a pattern": {'TEST_TITLE': '(test'},
            "'TEST_TITLE'] is empty": {'TEST_TITLE': ''},
            # Each item of a tuple is of its type, and the check of its values never meets another.
            "'LEFT_AFTER'] is a tuple of int, not ('12', '24')": {'LEFT_AFTER': ['12', '24']},
            "'LEFT_AFTER'] is a tuple of int, not (12.5,)": {'LEFT_AFTER': [12.5]},
            "'BANDED_STATUSES'] is a tuple of str, not (['T'],)": {'BANDED_STATUSES': [['T']]},
            "'REPLY_MINUTES'] is a tuple of float, not (5, None)": {'REPLY_MINUTES': (5, None)},
            # As many as the chart has views to switch between.
            "'LEFT_AFTER'] is at most 3 numbers": {'LEFT_AFTER': (6, 12, 24, 36)},
            # The two title patterns run in the database: only what Postgres reads as Python does.
            "'TEST_TITLE'] has \\b, which the database reads otherwise": {'TEST_TITLE': r'\btest\b'},
            "'HEADS_UP_TITLE'] has (?P": {'HEADS_UP_TITLE': r'(?P<h>heads up)'},
            "'HEADS_UP_TITLE'] has (?-": {'HEADS_UP_TITLE': r'(?-i:Heads) up'},
            "'TEST_TITLE'] has *+": {'TEST_TITLE': r'(test )*+event'},
            "'TEST_TITLE'] has [:": {'TEST_TITLE': r'^[[:alpha:]]+$'},
            "'TEST_TITLE'] has \\1": {'TEST_TITLE': r'(test)\1'},
            # Braces only as a bound both read: {n}, {n,} or {n,m}, each up to 255, with nothing else between them.
            "'TEST_TITLE'] has {,3}": {'TEST_TITLE': r'^\W*test\W{,3}$'},
            "'TEST_TITLE'] has {0,300}": {'TEST_TITLE': r'^te{0,300}st'},
            "'TEST_TITLE'] has {1, which": {'TEST_TITLE': r'test{1'},
            "'HEADS_UP_TITLE'] has {1, 2}": {'HEADS_UP_TITLE': r"head(s|['’]s)[\s-]{1, 2}up"},
            # And no quantifier after a lookaround, which Postgres refuses.
            "'TEST_TITLE'] has )*": {'TEST_TITLE': r'^(?:test|drill)(?=\W)*'},
            "'TEST_TITLE'] has )?": {'TEST_TITLE': r'(?<=\W)?test'},
            # A pattern too large to compile is refused as one, not by an error the check does not catch.
            "'IMMEDIATE_CALLOUT'] is not a pattern": {'IMMEDIATE_CALLOUT': 'a{4294967296}'},
            # Months that a date can be counted forward by.
            "'LEFT_AFTER'] is at most 120 months": {'LEFT_AFTER': (12, 24, 120000)},
            "'MAX_ENTRY_DAYS'] is at most 366 days": {'MAX_ENTRY_DAYS': 10 ** 9},
            "'SINGLE_DAY_HOURS'] is above zero": {'SINGLE_DAY_HOURS': 0},
            "'GUEST_FRIENDLY_TITLE'] is not a pattern": {'GUEST_FRIENDLY_TITLE': 'guests ('},
            "'LEFT_AFTER'] is one or more numbers above zero, each more than the last": {'LEFT_AFTER': (24, 12)},
            "'RESPONDERS_FULL'] is at least two more than RESPONDERS_THIN": {'RESPONDERS_THIN': 5,
                                                                              'RESPONDERS_FULL': 6},
            "'REPLY_MINUTES'] is two numbers above zero, the second more than the first": {'REPLY_MINUTES': [5]},
            "'BANDED_STATUSES'] is one to four statuses of members, each once": {'BANDED_STATUSES': ('T', 'T')},
        }
        for message, setting in wrong.items():
            with override_settings(ACTIVITY_REPORTS=setting):
                [error] = check_report_settings(None)
                self.assertEqual(error.id, 'main.E001')
                self.assertIn(message, error.msg)
                with self.assertRaisesMessage(ImproperlyConfigured, message):
                    report_settings()
        with override_settings(ACTIVITY_REPORTS=[('DAY_HOURS', 2)]):
            self.assertIn('is a dict of the keys to change', check_report_settings(None)[0].msg)
        self.assertEqual(check_report_settings(None), [])
        # A pattern that only Python reads may use what Python has, and a title pattern what both read alike.
        with override_settings(ACTIVITY_REPORTS={
                'GUEST_FRIENDLY_TITLE': r'(?-i:\sG$)', 'TEST_TITLE': r'^(?:drill|test)(?=\W|$)',
                'HEADS_UP_TITLE': r"^\W{0,3}head(s|['’]s)?[\s-]{1,}up\{1\}(\W{2}|$)"}):
            self.assertEqual(check_report_settings(None), [])


def pacific(month, day, hour):
    """A time in 2024, Pacific Standard Time (UTC-8)."""
    return datetime(2024, month, day, hour, tzinfo=dt_timezone.utc) + timedelta(hours=8)


class TeamRulesTestCase(ActivityTestCase):
    """Each key changes the rule it names; both sides are set here, so nothing rests on the defaults."""

    def titled(self, title, *args, **kwargs):
        event = self.make_event(*args, **kwargs)
        Event.objects.filter(pk=event.pk).update(title=title)
        return Event.objects.get(pk=event.pk)

    def test_test_title(self):
        drill = self.titled('Drill night', 'training', when(2024, 3, 10), attended=[self.member])
        test = self.titled('Test', 'training', when(2024, 3, 11), attended=[self.member])
        with override_settings(ACTIVITY_REPORTS={'TEST_TITLE': r'^drill(\W|$)'}):
            self.assertEqual(set(reported_events().filter(id__in=[drill.id, test.id])), {test})
        with override_settings(ACTIVITY_REPORTS={'TEST_TITLE': r'^test$'}):
            self.assertEqual(set(reported_events().filter(id__in=[drill.id, test.id])), {drill})

    def test_heads_up_title(self):
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
        # An operation never used is kept only if its title says it was a heads-up.
        warned = self.titled('Warning: search', 'operation', when(2024, 3, 10))
        with override_settings(ACTIVITY_REPORTS={'HEADS_UP_TITLE': r'(^|\W)warning(\W|$)'}):
            self.assertIn(warned, reported_events())
        with override_settings(ACTIVITY_REPORTS={'HEADS_UP_TITLE': r'(^|\W)alert(\W|$)'}):
            self.assertNotIn(warned, reported_events())

    def test_callout_template(self):
        self.paging_began()        # pages recorded, and carrying reply templates, from the usual days
        # From when pages carried reply templates, an operation that did not run was called off if a callout
        # page went out for it, and only a heads-up if not.
        operation = self.make_event('operation', when(2024, 3, 10), no_time=[self.member])
        page = Message.objects.create(author=self.other, text='Page', format='page', period=operation.period_set.first(),
                                      rsvp_template=RsvpTemplate.objects.create(name='Can you go?'))
        Message.objects.filter(id=page.id).update(created_at=operation.start_at)
        for callout, why in (('Can you go?', 'called_off'), ('Available?', 'heads_up')):
            with override_settings(ACTIVITY_REPORTS={'CALLOUT_TEMPLATE': callout}):
                self.assertEqual(self.not_run(), {operation.id: why}, callout)

    def test_day_hours_and_single_day_hours(self):
        # 10pm to 11am: 2 hours on the 5th and 11 on the 6th, 13 in all.
        start, end = pacific(3, 5, 22), pacific(3, 6, 11)
        for rules, days in (({'DAY_HOURS': 2, 'SINGLE_DAY_HOURS': 12}, {5: 2, 6: 11}),
                            ({'DAY_HOURS': 3, 'SINGLE_DAY_HOURS': 12}, {6: 13}),
                            ({'DAY_HOURS': 2, 'SINGLE_DAY_HOURS': 13}, {6: 13})):
            with override_settings(ACTIVITY_REPORTS=rules):
                self.assertEqual({d.day: h for d, h in day_hours(start, end, None, None).items()}, days, rules)
        with override_settings(ACTIVITY_REPORTS={'DAY_HOURS': 3, 'SINGLE_DAY_HOURS': 10}):
            self.assertIn('at least 3 hours', dict(glossary())['Day attended'])
            self.assertIn('10 hours or less as one day', dict(glossary())['Day attended'])
        # A setting of one is written in the singular.
        with override_settings(ACTIVITY_REPORTS={'DAY_HOURS': 1, 'SINGLE_DAY_HOURS': 1}):
            self.assertIn('at least 1 hour logged', dict(glossary())['Day attended'])
            self.assertIn('1 hour or less as one day', dict(glossary())['Day attended'])

    def test_max_entry_days(self):
        # Three days by the clock: a mistake, one day and no hours, where the limit is two.
        start, end = pacific(3, 5, 12), pacific(3, 8, 12)
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 3}):
            self.assertEqual(len(day_hours(start, end, None, None)), 4)
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 2}):
            self.assertEqual({d.day: h for d, h in day_hours(start, end, None, None).items()}, {5: 0})
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 1}):
            self.assertTrue(dict(glossary())['Mistaken times'].startswith('More than 1 day logged'))
