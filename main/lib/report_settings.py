"""The rules of the activity reports that a team sets for itself, from the
ACTIVITY_REPORTS setting: a dict of only the keys to change, each one left
out keeping its default here, which are BAMRU's. The reports read them from
report_settings(). At start-up a system check refuses a key that is not one
of these, a value of the wrong type, a pattern that does not compile, or a
value its key's check refuses, naming the key."""
import re
from dataclasses import dataclass, field, fields
from functools import cache
from typing import get_args, get_origin

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver

from main.lib.charts import MAX_VIEWS
from main.models import Member


def _above_zero(value, report_settings):
    return None if value > 0 else 'is above zero'


def _rising(value, report_settings):
    return None if value and all(number > 0 for number in value) and list(value) == sorted(set(value)) else (
        'is one or more numbers above zero, each more than the last')


def _a_view_each(value, report_settings):
    return _rising(value, report_settings) or (None if len(value) <= MAX_VIEWS else (
        'is at most {} numbers, one for each view the chart can switch between'.format(MAX_VIEWS)))


def _beyond_thin(value, report_settings):
    return None if value >= report_settings.RESPONDERS_THIN + 2 else (
        'is at least two more than RESPONDERS_THIN, so that some fall between')


def _two_rising(value, report_settings):
    return None if len(value) == 2 and not _rising(value, report_settings) else (
        'is two numbers above zero, the second more than the first')


def _member_statuses(value, report_settings):
    statuses = [code for code, _ in Member.TYPES if code not in Member.GUESTS]
    return None if 1 <= len(value) <= 4 and len(set(value)) == len(value) and set(value) <= set(statuses) else (
        'is one to four statuses of members, each once, of {}'.format(', '.join(statuses)))


def _escape_unsafe(letter):
    """An escaped letter or digit the database reads otherwise than Python: all but \s \S \w \W \d \D."""
    return letter.isalnum() and letter not in 'sSwWdD'


def _sql_unsafe(pattern):
    """What in a pattern the database would read otherwise than Python's re,
    or None. A pattern that a query runs (title__iregex) keeps to what both
    read alike, on Postgres and on SQLite, which runs Python's re: literal
    text, escaped punctuation, \s \S \w \W \d \D, classes, groups (...) and
    (?:...), lookaround, alternation, anchors and quantifiers, greedy or lazy.
    Not \b, which is a backspace to Postgres, or any other escaped letter or
    digit; not named or flagged groups, possessive repeats or POSIX classes."""
    i = 0
    while i < len(pattern):
        char, after = pattern[i], pattern[i + 1:i + 2]
        if char == '\\':
            if _escape_unsafe(after):
                return '\\' + after
            i += 2
        elif char == '[':
            # A class runs to the first ] that is not its first character.
            end = i + 1 + (pattern[i + 1:i + 2] == '^')
            end += pattern[end:end + 1] == ']'
            while end < len(pattern) and pattern[end] != ']':
                if pattern[end] == '\\':
                    if _escape_unsafe(pattern[end + 1:end + 2]):
                        return pattern[end:end + 2]
                    end += 1
                elif pattern[end] == '[' and pattern[end + 1:end + 2] in (':', '.', '='):
                    return pattern[end:end + 2]
                end += 1
            i = end + 1
        elif char == '(' and after == '?' and not pattern.startswith(('(?:', '(?=', '(?!', '(?<=', '(?<!'), i):
            return pattern[i:i + 3]
        elif char in '*+?}' and after == '+':
            return char + after
        else:
            i += 1
    return None


def _rule(default, *, pattern=False, check=None):
    """A key's default, with what else its value must be: a regular
    expression (`pattern`), read ignoring case, and one a query runs if
    'sql' (_sql_unsafe); and `check`, given the value and the settings,
    which returns what is wrong with it, or None."""
    return field(default=default, metadata={'pattern': pattern, 'check': check})


@dataclass(frozen=True)
class ReportSettings:
    """The activity reports' rules: one attribute for each key of ACTIVITY_REPORTS."""
    # Events no report counts, by their title, ignoring case and a leading [tag]: tests and demonstrations.
    TEST_TITLE: str = _rule(r"^\W*(\[[^]]*\]\s*)?(test(\s+event)?\W*$|demo\s+event)", pattern='sql')
    # A title saying an operation was only a heads-up, which may have gone by email. (Word edges are
    # written out, as \b means a backspace to Postgres, which reads both patterns.)
    HEADS_UP_TITLE: str = _rule(r"(^|\W)head(s|['’]s)[\s-]+up(\W|$)", pattern='sql')
    # The reply template of an operation's callout pages, which ask who can go.
    CALLOUT_TEMPLATE: str = 'Available?'
    # The reply template of an operation's heads-up pages, which warn that a callout may follow.
    HEADS_UP_TEMPLATE: str = 'Heads Up'
    # The hours of an entry's time on a calendar day that make it a day attended.
    DAY_HOURS: float = _rule(2, check=_above_zero)
    # An entry of at most this many hours is one day attended, even across midnight.
    SINGLE_DAY_HOURS: float = _rule(12, check=_above_zero)
    # An entry longer than this many days by the local clock is a mistake: one day, and no hours.
    MAX_ENTRY_DAYS: int = _rule(7, check=_above_zero)

    # The unit report.
    # Trainings guests may come to, by their title, so that a day at one is no day towards joining: SAR Basic;
    # those whose title says "guest", other than "no guests", "not for guests" or a guest lecturer, speaker,
    # instructor or presenter; and those marked G: "* G", "*G", "G*", "(G)", or a capital G at the very end
    # ("Rope rescue G"). Words may have any spaces or hyphens between them, so a match starts where those
    # before "guests" (or "for guests") do: after anything but a space or a hyphen, and not after "no" or "not".
    GUEST_FRIENDLY_TITLE: str = _rule(
        r'sar[\s-]*basic'
        r'|(?<![\s-])(?:(?<!\bno)(?<!\bfor)|(?<!\bnot)[\s-]*\bfor)'
        r'[\s-]*\bguests?\b(?![\s-]+(?:lectur|speak|instruct|present))'
        r'|\*\s*g\b|\bg\*|\(g\)'
        r'|(?-i:\sG\s*$)', pattern=True)
    # An immediate callout's page, by how its text starts: the DO starts one with the word, after the name of
    # the operation's period where the page form puts it ("<title> OP1:"); a page that repeats, answers,
    # forwards or updates one puts its own word before that, perhaps numbered, perhaps more than once
    # ("Repage 2:", "Repage #2:", "Re:", "Fwd:", "UPDATE #1:"). Read by Python only: the possessive *+ keeps
    # the match linear in the page's length, as no word put before is read twice.
    IMMEDIATE_CALLOUT: str = _rule(
        r'\W*(?:(?:re-?page|re|fwd?|update)\b[^\w#]*(?:#?\d+[^\w#]*)?)*+(?:\w.*?\bop\d+:\W*)?immediate\b',
        pattern=True)
    # How the unit report's glossary says which callout pages IMMEDIATE_CALLOUT matches.
    IMMEDIATE_CALLOUT_SAID: str = ('starting "Immediate", or with "Immediate" after the operation\'s name as the page '
                                   'form begins a page, repages included')
    # Joining, read from activity as no date for it is kept: the days at operations or trainings not open to
    # guests on which a member has joined; with fewer, they joined on their first event.
    JOINED_AT: int = _rule(3, check=_above_zero)
    # Leaving: the months without an operation, training or community event after which a member has left.
    # The first is the rule for being active; the joining and leaving chart can be switched to the others.
    LEFT_AFTER: tuple[int, ...] = _rule((12, 24, 36), check=_a_view_each)
    # The most responders an operation can have and be one of the fewest, as the unit report splits them.
    RESPONDERS_THIN: int = _rule(3, check=_above_zero)
    # The fewest responders that make an operation one of the most; those between RESPONDERS_THIN and this are
    # the middle.
    RESPONDERS_FULL: int = _rule(8, check=_beyond_thin)
    # How soon members replied to a callout page, in minutes: within the first, up to the second, or later.
    REPLY_MINUTES: tuple[float, ...] = _rule((5, 60), check=_two_rising)
    # How soon the first responder left home on an immediate callout, in minutes: within the first, up to the
    # second, or later.
    DEPARTURE_MINUTES: tuple[float, ...] = _rule((30, 60), check=_two_rising)
    # Stretches in the field: a one-day stretch of more than these hours, door to door, is a long day.
    LONG_DAY: float = _rule(12, check=_above_zero)
    # Where the unit report starts: years without any record are shown as empty columns, but a run of this many
    # empty years cuts off what came before it, as a stray early record, not the start of the records.
    STRAY_BEFORE: int = _rule(3, check=_above_zero)
    # The statuses the status chart gives a band of their own, newest first, as they are drawn lightest: one to
    # four codes of Member.TYPES, as the chart has four steps of blue, and not a guest's. Any other is Other.
    BANDED_STATUSES: tuple[str, ...] = _rule(('T', 'FM', 'TM'), check=_member_statuses)
    # The year from which most operations have their times logged: what the unit report reads from those times
    # (whether an operation ran, who went) is grey before it.
    OPERATION_TIMES_FROM: int = 2013

    def __post_init__(self):
        for key in fields(self):
            value = getattr(self, key.name)
            if not _of_type(value, key.type):
                raise ImproperlyConfigured('ACTIVITY_REPORTS[{!r}] is a {}, not {!r}'.format(
                    key.name, _type_name(key.type), value))
            if key.metadata.get('pattern'):
                if not value:
                    raise ImproperlyConfigured('ACTIVITY_REPORTS[{!r}] is empty, which every title matches'.format(
                        key.name))
                try:
                    re.compile(value, re.IGNORECASE)
                except re.error as error:
                    raise ImproperlyConfigured('ACTIVITY_REPORTS[{!r}] is not a pattern: {}'.format(key.name, error))
                unsafe = key.metadata['pattern'] == 'sql' and _sql_unsafe(value)
                if unsafe:
                    raise ImproperlyConfigured('ACTIVITY_REPORTS[{!r}] has {}, which the database reads otherwise than '
                                               'Python; see _sql_unsafe'.format(key.name, unsafe))
            wrong = key.metadata.get('check') and key.metadata['check'](value, self)
            if wrong:
                raise ImproperlyConfigured('ACTIVITY_REPORTS[{!r}] {}: {!r}'.format(key.name, wrong, value))


def _of_type(value, kind):
    """Whether a value is of a key's type, its annotation: a float may be an
    int, a tuple's items are of its own type, and a bool is none of these."""
    if get_origin(kind) is tuple:
        return isinstance(value, tuple) and all(_of_type(item, get_args(kind)[0]) for item in value)
    return not isinstance(value, bool) and isinstance(value, (int, float) if kind is float else kind)


def _type_name(kind):
    return 'tuple of {}'.format(get_args(kind)[0].__name__) if get_origin(kind) is tuple else kind.__name__


def _read(setting):
    """The ReportSettings of an ACTIVITY_REPORTS value: its keys over the
    defaults. A list given for a tuple is read as one."""
    if not isinstance(setting, dict):
        raise ImproperlyConfigured('ACTIVITY_REPORTS is a dict of the keys to change')
    keys = {key.name: key for key in fields(ReportSettings)}
    unknown = sorted(set(setting) - set(keys))
    if unknown:
        raise ImproperlyConfigured('ACTIVITY_REPORTS has no key {}; its keys are {}'.format(
            ', '.join(map(repr, unknown)), ', '.join(keys)))
    return ReportSettings(**{name: tuple(value) if get_origin(keys[name].type) is tuple and isinstance(value, list)
                             else value for name, value in setting.items()})


@cache
def report_settings():
    """The activity reports' rules: ACTIVITY_REPORTS over the defaults, read
    once, and again when the setting changes (in a test)."""
    return _read(getattr(settings, 'ACTIVITY_REPORTS', {}))


@receiver(setting_changed)
def _read_again(setting, **kwargs):
    if setting == 'ACTIVITY_REPORTS':
        report_settings.cache_clear()


@checks.register()
def check_report_settings(app_configs, **kwargs):
    """ACTIVITY_REPORTS as report_settings() reads it, at start-up: an error
    naming the key, rather than a report that fails when it is first read."""
    try:
        _read(getattr(settings, 'ACTIVITY_REPORTS', {}))
    except ImproperlyConfigured as error:
        return [checks.Error(str(error), id='main.E001')]
    return []
