"""The activity reports' settings (main.lib.report_settings): the defaults, a team's keys over them, and the
values refused at start-up, with a warning, each keeping its default."""
import io
import re
from dataclasses import fields
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import get_origin

from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
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
            # Nor a hyphen in a class but first, last, escaped or between two plain characters, the first not
            # itself the end of a range, nor a bound on a group with a bound inside, which Postgres refuses (a
            # range to or from an escape Python refuses too).
            "'TEST_TITLE'] has 9-_, which": {'TEST_TITLE': r'^(test|drill)[a-z0-9-_ ]*$'},
            "'HEADS_UP_TITLE'] has z-0, which": {'HEADS_UP_TITLE': r'head[a-z-0]*up'},
            "'TEST_TITLE'] has b-c, which": {'TEST_TITLE': r'^[a-b-c]test'},
            "'TEST_TITLE'] has ){1,255}, which": {'TEST_TITLE': r'(\w{1,255}\s?){1,255}'},
            "'TEST_TITLE'] has ){3}, which": {'TEST_TITLE': r'^((?:te){2}s)t{3}|((t{2})e)st{1}x{3}|((t{2})est){3}'},
            # Numbers are finite, and an hour count one a time can be counted forward by.
            "'LONG_DAY'] is a finite number, not inf": {'LONG_DAY': float('inf')},
            "'DAY_HOURS'] is a finite number, not nan": {'DAY_HOURS': float('nan')},
            "'REPLY_MINUTES'] is finite numbers, not (5, inf)": {'REPLY_MINUTES': (5, float('inf'))},
            "'LONG_DAY'] is at most 8784 hours": {'LONG_DAY': 1e300},
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
        defaults = ReportSettings()
        for message, setting in wrong.items():
            with override_settings(ACTIVITY_REPORTS=setting):
                [warning] = check_report_settings(None)
                self.assertEqual((warning.id, warning.level), ('main.W001', checks.WARNING))
                self.assertIn(message, warning.msg)
                # The reports run on the key's default in its place.
                refused = re.match(r"'(\w+)'\]", message)
                if refused:
                    key = refused[1]
                    self.assertEqual(getattr(report_settings(), key), getattr(defaults, key), message)
        with override_settings(ACTIVITY_REPORTS=[('DAY_HOURS', 2)]):
            self.assertIn('is a dict of the keys to change', check_report_settings(None)[0].msg)
            self.assertEqual(report_settings(), defaults)
        self.assertEqual(check_report_settings(None), [])
        # A pattern that only Python reads may use what Python has, and a title pattern what both read alike.
        with override_settings(ACTIVITY_REPORTS={
                'GUEST_FRIENDLY_TITLE': r'(?-i:\sG$)',
                'TEST_TITLE': r'^[^-a-z]*[-0-9a-z_ ]*(?:drill|te(?:s){1}t)(?:x{2})*(?=\W|$)',
                'HEADS_UP_TITLE': r"^\W{0,3}head(s|['’]s)?[\s-]{1,}up\{1\}(\W{2}|$)"}):
            self.assertEqual(check_report_settings(None), [])


class NoContactTestCase(SimpleTestCase):
    def test_a_no_contact_status_is_never_given_a_band_of_its_own(self):
        # The status chart names each banded status, and a no-contact status's name is never shown on the reports
        # (Member.NO_CONTACT): one is refused, with a warning that lists the statuses a team may band, and the
        # default kept. A guest status was refused already.
        for banded in (('MN',), ('T', 'MN'), ('GN',)):
            with self.subTest(banded), override_settings(ACTIVITY_REPORTS={'BANDED_STATUSES': banded}):
                [warning] = check_report_settings(None)
                self.assertEqual(warning.id, 'main.W001')
                # The statuses it may band end at MA: the warning repeats the team's own value after them.
                self.assertIn("'BANDED_STATUSES'] is one to four statuses of members, each once, of TM, FM, T, R, S, "
                              "A, MA: ", warning.msg)
                self.assertEqual(report_settings().BANDED_STATUSES, ReportSettings().BANDED_STATUSES)


class RefusedValueTestCase(SimpleTestCase):
    """A team's refused value warns at start-up and keeps its default, so that migrate and the task queue still
    start and the reports run, on checked values only."""

    def test_a_team_may_say_nothing_of_how_its_joining_rule_was_checked_but_not_give_a_number(self):
        with override_settings(ACTIVITY_REPORTS={'JOINED_CHECKED': ''}):
            self.assertEqual(check_report_settings(None), [])
            self.assertEqual(report_settings().JOINED_CHECKED, '')
        with override_settings(ACTIVITY_REPORTS={'JOINED_CHECKED': 5}):
            self.assertEqual([(w.id, w.level) for w in check_report_settings(None)], [('main.W001', checks.WARNING)])
            self.assertEqual(report_settings().JOINED_CHECKED, ReportSettings().JOINED_CHECKED)

    def test_a_refused_value_warns_and_the_reports_use_its_default_beside_the_team_s_other_keys(self):
        defaults = ReportSettings()
        team = {'DAY_HOURS': -1, 'SINGLE_DAY_HOURS': 10, 'TEST_TITLE': r'\btest\b', 'NO_SUCH_KEY': 1}
        with override_settings(ACTIVITY_REPORTS=team):
            warnings = check_report_settings(None)
            self.assertEqual([(w.id, w.level) for w in warnings], [('main.W001', checks.WARNING)] * 3)
            said = '\n'.join(w.msg for w in warnings)
            self.assertIn("ACTIVITY_REPORTS has no key 'NO_SUCH_KEY'", said)
            self.assertIn("ACTIVITY_REPORTS['DAY_HOURS'] is above zero: -1; its default is used", said)
            self.assertIn("ACTIVITY_REPORTS['TEST_TITLE'] has \\b", said)
            read = report_settings()
            self.assertEqual((read.DAY_HOURS, read.SINGLE_DAY_HOURS, read.TEST_TITLE),
                             (defaults.DAY_HOURS, 10, defaults.TEST_TITLE))
            # As migrate and qcluster check at start-up, failing on errors: a warning stops neither.
            call_command('check', fail_level='ERROR', stdout=io.StringIO(), stderr=io.StringIO())

    def test_a_good_value_that_leaves_a_default_wrong_is_refused_in_its_place(self):
        # RESPONDERS_THIN 10, against RESPONDERS_FULL's default of 8, which must be at least two more.
        with override_settings(ACTIVITY_REPORTS={'RESPONDERS_THIN': 10}):
            [warning] = check_report_settings(None)
            self.assertIn("ACTIVITY_REPORTS['RESPONDERS_THIN'] is refused, as with it", warning.msg)
            self.assertEqual((report_settings().RESPONDERS_THIN, report_settings().RESPONDERS_FULL), (3, 8))
        # Both set, the second too few: the first is kept.
        with override_settings(ACTIVITY_REPORTS={'RESPONDERS_THIN': 5, 'RESPONDERS_FULL': 6}):
            self.assertEqual((report_settings().RESPONDERS_THIN, report_settings().RESPONDERS_FULL), (5, 8))

    PAIR = ('RESPONDERS_THIN', 'RESPONDERS_FULL')

    def assert_read(self, setting, used, warned):
        """The check warns once for each key in `warned`, in that order, each sentence naming it first; and the
        reports use `used` for RESPONDERS_THIN and RESPONDERS_FULL. Nothing is raised."""
        with override_settings(ACTIVITY_REPORTS=setting):
            warnings = check_report_settings(None)
            self.assertEqual([(w.id, w.msg.split(']', 1)[0]) for w in warnings],
                             [('main.W001', "ACTIVITY_REPORTS[{!r}".format(key)) for key in warned], setting)
            read = report_settings()
            self.assertEqual(tuple(getattr(read, key) for key in self.PAIR), used, setting)

    def test_both_responder_keys_given_together_never_raise(self):
        thin, full = self.PAIR
        # The team's FULL is refused, and then the default FULL is too, against the team's THIN: THIN is refused in
        # its place, so both keys are named and both defaults used.
        self.assert_read({thin: 10, full: 5}, (3, 8), [full, thin])
        self.assert_read({thin: 7, full: 8}, (3, 8), [full, thin])          # FULL one short
        self.assert_read({thin: 10, full: 'x'}, (3, 8), [full, thin])       # FULL refused for its kind
        # As before.
        self.assert_read({thin: 10}, (3, 8), [thin])
        self.assert_read({thin: 5, full: 6}, (5, 8), [full])
        self.assert_read({thin: 6, full: 5}, (6, 8), [full])
        self.assert_read({thin: 7, full: 9}, (7, 9), [])

    def test_a_thin_of_the_wrong_kind_is_refused_before_full_is_checked_against_it(self):
        thin, full = self.PAIR
        for wrong in ('3', None, [3], 3.5, True):
            self.assert_read({thin: wrong}, (3, 8), [thin])
        # FULL is then checked against the default THIN of 3, and 9 is good against it.
        self.assert_read({thin: '3', full: 9}, (3, 9), [thin])

    def test_nothing_a_team_can_type_makes_the_reader_raise(self):
        # Every key with values of the wrong kind or out of its range, alone; and the two keys that read each
        # other given together, every way. Each read gives checked settings and warns of every key it refused.
        wrong = {int: [None, '3', [3], (3,), True, 3.5, -1, 0, float('nan'), 10 ** 9],
                 float: [None, '2', [2], True, float('nan'), float('inf'), -1, 0, 1e300],
                 str: [None, 3, '', '(', r'\btest', '[a-z-0]', 'a{300}', ['a']],
                 tuple: [None, '12', [None], ['12'], [], [0], [24, 12], [float('inf')], (1, 2, 3, 4, 5), 12]}
        settings_to_read = [{key.name: value} for key in fields(ReportSettings)
                            for value in wrong[get_origin(key.type) or key.type]]
        values = [None, '3', 3.5, True, -1, 0, *range(1, 13), 15]
        settings_to_read += [{self.PAIR[0]: a, self.PAIR[1]: b} for a in values for b in values]
        defaults = ReportSettings()
        for setting in settings_to_read:
            with override_settings(ACTIVITY_REPORTS=setting):
                read, warned = report_settings(), ' '.join(w.msg for w in check_report_settings(None))
            self.assertIsInstance(read, ReportSettings)
            for key, value in setting.items():
                used = getattr(read, key)
                if not (used == value or isinstance(value, list) and used == tuple(value)):
                    self.assertEqual(used, getattr(defaults, key), setting)     # refused: its default is used
                    self.assertIn("ACTIVITY_REPORTS[{!r}]".format(key), warned, setting)

    def test_no_unchecked_value_reaches_the_reports(self):
        # The settings the reports read are a ReportSettings, which refuses a wrong value itself.
        with self.assertRaisesMessage(ImproperlyConfigured, "ACTIVITY_REPORTS['DAY_HOURS'] is above zero"):
            ReportSettings(DAY_HOURS=-1)
        with override_settings(ACTIVITY_REPORTS={'DAY_HOURS': -1}):
            self.assertIsInstance(report_settings(), ReportSettings)


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
            self.assertIn('Up to 10 hours counts as one day', dict(glossary())['Day attended'])
            self.assertIn('More than 10 hours counts each date with at least 3 hours on it.', dict(glossary())['Day attended'])
        # A setting of one is written in the singular.
        with override_settings(ACTIVITY_REPORTS={'DAY_HOURS': 1, 'SINGLE_DAY_HOURS': 1}):
            self.assertIn('Up to 1 hour counts as one day', dict(glossary())['Day attended'])
            self.assertIn('More than 1 hour counts each date with at least 1 hour on it.', dict(glossary())['Day attended'])

    def test_the_immediate_callout_sentence_says_what_the_default_pattern_matches(self):
        # The sentence the unit glossary fills in after "An operation with a callout page", and each thing it
        # says, read by the default pattern as the report reads it: from the start of a page, ignoring case.
        rules = report_settings()
        self.assertEqual(rules.IMMEDIATE_CALLOUT_SAID,
                         'that starts with "Immediate", or has "Immediate" straight after the operation\'s name and '
                         'number, which is how the page form starts a page. A repage, reply, forward or update of '
                         'such a page counts as well')
        starts_immediate = re.compile(rules.IMMEDIATE_CALLOUT, re.IGNORECASE)
        said = [('starts with "Immediate"', 'Immediate callout: search'),
                ('straight after the name and number', 'Ridge search OP1: Immediate callout'),
                ('a repage', 'Repage 2: Ridge search OP1: Immediate callout'), ('a reply', 'Re: Immediate callout'),
                ('a forward', 'Fwd: Immediate callout'), ('an update', 'UPDATE #1: Ridge search OP1: Immediate')]
        for claim, text in said:
            self.assertTrue(starts_immediate.match(text), claim)
        # After the name without its number, or later in the page, is not what the sentence says, nor matched.
        for text in ('Ridge search: Immediate callout', 'Ridge search OP1: search, immediate callout'):
            self.assertFalse(starts_immediate.match(text), text)

    def test_max_entry_days(self):
        # Three days by the clock: a mistake, one day and no hours, where the limit is two.
        start, end = pacific(3, 5, 12), pacific(3, 8, 12)
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 3}):
            self.assertEqual(len(day_hours(start, end, None, None)), 4)
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 2}):
            self.assertEqual({d.day: h for d, h in day_hours(start, end, None, None).items()}, {5: 0})
        with override_settings(ACTIVITY_REPORTS={'MAX_ENTRY_DAYS': 1}):
            self.assertTrue(dict(glossary())['Time left out'].startswith('More than 1 day logged'))
