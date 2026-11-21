"""The rules of the activity reports that a team sets for itself, from the
ACTIVITY_REPORTS setting: a dict of only the keys to change, each one left
out keeping its default here, which are BAMRU's. The reports read them from
report_settings(). A key that is not one of these, a value of the wrong
type or a number that is not finite, a pattern that does not compile, or a
value its key's check refuses is refused: a system check warns of it at
start-up, naming the key, and the reports use that key's default, with the
team's other keys, so that they only ever run on checked values. A warning,
not an error, so that migrate and the task queue still start."""
import math
import re
from dataclasses import dataclass, field, fields
from datetime import date
from functools import cache
from types import SimpleNamespace
from typing import get_args, get_origin

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver

from main.lib.charts import MAX_MEASURES, MAX_VIEWS
from main.models import Member


def _above_zero(value, report_settings):
    return None if value > 0 else 'is above zero'


def _rising(value, report_settings):
    return None if value and all(number > 0 for number in value) and list(value) == sorted(set(value)) else (
        'is one or more numbers above zero, each more than the last')


def _a_view_each(value, report_settings):
    return _rising(value, report_settings) or (None if len(value) <= MAX_VIEWS else (
        'is at most {} numbers, one for each view the chart can switch between'.format(MAX_VIEWS))) or (
        None if max(value) <= 120 else 'is at most 120 months, ten years, each')


def _beyond_thin(value, report_settings):
    return None if value >= report_settings.RESPONDERS_THIN + 2 else (
        'is at least two more than RESPONDERS_THIN, so that some fall between')


def _two_rising(value, report_settings):
    return None if len(value) == 2 and not _rising(value, report_settings) else (
        'is two numbers above zero, the second more than the first')


def _up_to(most, unit):
    """The check of a number above zero and at most `most` (of `unit`)."""
    def check(value, report_settings):
        return _above_zero(value, report_settings) or (None if value <= most else 'is at most {} {}'.format(most, unit))
    return check


def _a_year(value, report_settings):
    return None if date.min.year <= value <= date.max.year else 'is a year, {} to {}'.format(date.min.year,
                                                                                            date.max.year)


def _no_limit_or_up_to_20_seconds(value, report_settings):
    return None if 0 <= value <= 20 else 'is 0, for no limit, or a number of seconds up to 20'


def _member_statuses(value, report_settings):
    # Not a guest's, as guests are not counted with members; nor a no-contact status, whose name the reports never
    # show (Member.NO_CONTACT), as the status chart names each status banded.
    statuses = [code for code, _ in Member.TYPES if code not in Member.GUESTS and code not in Member.NO_CONTACT]
    fits = 1 <= len(value) <= MAX_MEASURES and len(set(value)) == len(value) and set(value) <= set(statuses)
    return None if fits else 'is 1 to {} statuses of members, each once, of {}'.format(MAX_MEASURES, ', '.join(statuses))


def _escape_unsafe(letter):
    """An escaped letter or digit the database reads otherwise than Python: all but \s \S \w \W \d \D."""
    return letter.isalnum() and letter not in 'sSwWdD'


# A bound both read alike: {n}, {n,} or {n,m}, with no spaces, as Postgres bounds go up to 255.
_BOUND = re.compile(r'\{(\d{1,3})(?:,(\d{0,3}))?\}')


def _class_unsafe(pattern, start):
    """What in the class at pattern[start] (its [) the database would read
    otherwise than Python, or refuses, as for _sql_unsafe, or None; and
    where the class ends, at its ]. A class runs to the first ] that is not
    its first character. A hyphen is a character first or last, or escaped;
    otherwise it makes a range of the plain characters either side, the
    first not itself the end of a range: Postgres refuses a range from or to
    an escape, or one that follows on from another ([a-z0-9-_])."""
    end = start + 1 + (pattern[start + 1:start + 2] == '^')
    first = end
    end += pattern[end:end + 1] == ']'
    plain = end > first             # whether the item before is a plain character, which may begin a range
    while end < len(pattern) and pattern[end] != ']':
        char = pattern[end]
        if char == '\\':
            if _escape_unsafe(pattern[end + 1:end + 2]):
                return pattern[end:end + 2], end
            end, plain = end + 2, False
        elif char == '[' and pattern[end + 1:end + 2] in (':', '.', '='):
            return pattern[end:end + 2], end
        elif char == '-' and end > first and pattern[end + 1:end + 2] not in (']', ''):
            to = pattern[end + 1]
            if not plain or to in '\\-[':
                return pattern[end - 1:end + 2 + (to == '\\')], end
            end, plain = end + 2, False
        else:
            end, plain = end + 1, True
    return None, end


def _sql_unsafe(pattern):
    """What in a pattern the database would read otherwise than Python's re,
    or refuses, or None. A pattern that a query runs (title__iregex) keeps to
    what both read alike, on Postgres and on SQLite, which runs Python's re:
    literal text, escaped punctuation, \s \S \w \W \d \D, classes
    (_class_unsafe), groups (...) and (?:...), lookaround, alternation,
    anchors and quantifiers, greedy or lazy, braces only as a bound (_BOUND)
    up to 255. Not \b, which is a backspace to Postgres, or any other escaped
    letter or digit; not named or flagged groups, possessive repeats, a
    repeated lookaround, a bound on a group with a bound inside, which
    Postgres finds too complex, other braces, such as {,3}, which Postgres
    reads as text, or POSIX classes."""
    i, groups = 0, []           # for each group open, [whether it is a lookaround, whether a bound is inside]
    while i < len(pattern):
        char, after = pattern[i], pattern[i + 1:i + 2]
        if char == '\\':
            if _escape_unsafe(after):
                return '\\' + after
            i += 2
        elif char == '[':
            unsafe, end = _class_unsafe(pattern, i)
            if unsafe:
                return unsafe
            i = end + 1
        elif char == '(':
            if after == '?' and not pattern.startswith(('(?:', '(?=', '(?!', '(?<=', '(?<!'), i):
                return pattern[i:i + 3]
            groups.append([pattern.startswith(('(?=', '(?!', '(?<=', '(?<!'), i), False])
            i += 1
        elif char == ')' and groups:
            lookaround, bounded = groups.pop()
            if lookaround and after and after in '*+?{':
                return char + after
            bound = _BOUND.match(pattern, i + 1)
            if bounded and bound:
                return char + bound.group()
            if bounded and groups:
                groups[-1][1] = True
            i += 1
        elif char == '{':
            bound = _BOUND.match(pattern, i)
            if not bound or max(int(n or 0) for n in bound.groups()) > 255:
                end = pattern.find('}', i)
                return pattern[i:] if end < 0 else pattern[i:end + 1]
            if groups:
                groups[-1][1] = True
            i = bound.end()
            if pattern[i:i + 1] == '+':
                return '}+'
        elif char in '*+?' and after == '+':
            return char + after
        else:
            i += 1
    return None


def _rule(default, *, pattern=False, check=None, reads=()):
    """A key's default, with what else its value must be: a regular
    expression (`pattern`), read ignoring case, and one a query runs if
    'sql' (_sql_unsafe); and `check`, given the value and the settings,
    which returns what is wrong with it, or None, reading the keys in
    `reads` besides its own."""
    return field(default=default, metadata={'pattern': pattern, 'check': check, 'reads': reads})


@dataclass(frozen=True)
class ReportSettings:
    """The activity reports' rules: one attribute for each key of ACTIVITY_REPORTS."""
    # Events no report counts, by their title, ignoring case and a leading [tag]: tests and demonstrations.
    TEST_TITLE: str = _rule(r"^\W*(\[[^]]*\]\s*)?(test(\s+event)?\W*$|demo\s+event)", pattern='sql')
    # A title saying an operation was only a heads-up, which may have gone by email. (Word edges are
    # written out, as \b means a backspace to Postgres, which reads both patterns.)
    HEADS_UP_TITLE: str = _rule(r"(^|\W)head(s|['’]s)[\s-]+up(\W|$)", pattern='sql')
    # TODO: the page form (main/views/message_views.py, format_convert) names these same two reply templates
    # in its own code, so a team that renames one must change it in both places. A later change should have
    # the form read them from here.
    # The reply template of an operation's callout pages, which ask who can go.
    CALLOUT_TEMPLATE: str = 'Available?'
    # The reply template of an operation's heads-up pages, which warn that a callout may follow.
    HEADS_UP_TEMPLATE: str = 'Heads Up'
    # The hours of an entry's time on a calendar day that make it a day attended.
    DAY_HOURS: float = _rule(2, check=_above_zero)
    # An entry of at most this many hours is one day attended, even across midnight.
    SINGLE_DAY_HOURS: float = _rule(12, check=_above_zero)
    # An entry longer than this many days by the local clock is a mistake: one day, and no hours.
    MAX_ENTRY_DAYS: int = _rule(7, check=_up_to(366, 'days'))
    # The member page's Last table: the longest, in seconds, that its queries may run between them, on Postgres,
    # before the page shows without it: up to 20, as the server ends a page at 30 (gunicorn's timeout,
    # deploy/azure_startup.sh), or 0 for no limit but the server's.
    LAST_TABLE_SECONDS: float = _rule(5, check=_no_limit_or_up_to_20_seconds)

    # The unit report.
    # An immediate callout's page, by how its text starts: the DO starts one with the word, after the name of
    # the operation's period where the page form puts it ("<title> OP1:"); a page that repeats, answers,
    # forwards or updates one puts its own word before that, perhaps numbered, perhaps more than once
    # ("Repage 2:", "Repage #2:", "Re:", "Fwd:", "UPDATE #1:"). Read by Python only: the possessive *+ keeps
    # the match linear in the page's length, as no word put before is read twice.
    IMMEDIATE_CALLOUT: str = _rule(
        r'\W*(?:(?:re-?page|re|fwd?|update)\b[^\w#]*(?:#?\d+[^\w#]*)?)*+(?:\w.*?\bop\d+:\W*)?immediate\b',
        pattern=True)
    # How the unit report's glossary says which callout pages IMMEDIATE_CALLOUT matches, after "An operation
    # with a callout page" and before a full stop.
    IMMEDIATE_CALLOUT_SAID: str = ('that starts with "Immediate", or has "Immediate" straight after the operation\'s '
                                   'name and number, which is how the page form starts a page. A repage, reply, '
                                   'forward or update of such a page counts as well')
    # The certificate type whose kinds are the endorsements named below and in BANDED_STATUSES.
    ENDORSEMENTS: str = 'Endorsements'
    # Joining: the endorsement whose date, or the year its comment starts with, is the day a member joined. Without
    # either, a member joined on their first day at a training or an operation.
    JOINED_ENDORSEMENT: str = 'T'
    # The endorsements whose dates are promotions, each to the member status of the same code: an option each of the
    # chart of promotions' switch, the first shown to start with.
    PROMOTIONS: tuple[str, ...] = _rule(('FM', 'TM'), check=_member_statuses)
    # Becoming inactive: the months without an operation, training or community event after which a member is
    # inactive (left, in the code's names). The first is the rule for being active; the chart of members joining
    # and becoming inactive can be switched to the others.
    LEFT_AFTER: tuple[int, ...] = _rule((12, 24, 36), check=_a_view_each)
    # The most responders an operation can have and be one of the fewest, as the unit report splits them.
    RESPONDERS_THIN: int = _rule(3, check=_above_zero)
    # The fewest responders that make an operation one of the most; those between RESPONDERS_THIN and this are
    # the middle.
    RESPONDERS_FULL: int = _rule(8, check=_beyond_thin, reads=('RESPONDERS_THIN',))
    # How soon members replied to a callout page, in minutes: within the first, up to the second, or later.
    REPLY_MINUTES: tuple[float, ...] = _rule((5, 60), check=_two_rising)
    # How soon the first responder left home on an immediate callout, in minutes: within the first, up to the
    # second, or later.
    DEPARTURE_MINUTES: tuple[float, ...] = _rule((30, 60), check=_two_rising)
    # Stretches in the field: a one-day stretch of more than these hours, door to door, is a long day.
    LONG_DAY: float = _rule(12, check=_up_to(366 * 24, 'hours'))
    # Where the unit report starts: years without any record are shown as empty columns, but a run of this many
    # empty years cuts off what came before it, as a stray early record, not the start of the records.
    STRAY_BEFORE: int = _rule(3, check=_above_zero)
    # The statuses the status chart gives a band of their own, newest first, as they are drawn lightest: one to
    # four codes of Member.TYPES, as the chart has four steps of blue, and not a guest's or a no-contact one's.
    # Any other is Other.
    BANDED_STATUSES: tuple[str, ...] = _rule(('T', 'FM', 'TM'), check=_member_statuses)
    # The year from which most operations have their times logged: what the unit report reads from those times
    # (whether an operation ran, who went) is grey before it.
    OPERATION_TIMES_FROM: int = _rule(2013, check=_a_year)

    def __post_init__(self):
        # The one gate every value passes: no ReportSettings holds a value its key refuses.
        for key in fields(self):
            wrong = _wrong(key, getattr(self, key.name), self)
            if wrong:
                raise ImproperlyConfigured(wrong)


def _wrong_kind(key, value):
    """What is wrong with a value's kind for a key (a field of ReportSettings):
    not of its type, or a number that is not finite, as a sentence naming
    the key; or None."""
    if not _of_type(value, key.type):
        return 'ACTIVITY_REPORTS[{!r}] is a {}, not {!r}'.format(key.name, _type_name(key.type), value)
    several = isinstance(value, tuple)
    numbers = value if several else [value]
    if any(isinstance(number, float) and not math.isfinite(number) for number in numbers):
        return 'ACTIVITY_REPORTS[{!r}] is {}, not {!r}'.format(
            key.name, 'finite numbers' if several else 'a finite number', value)
    return None


def _wrong(key, value, report_settings):
    """What is wrong with a value for a key (a field of ReportSettings), the
    others read from `report_settings`, as a sentence naming the key; or
    None. A check that reads other keys is made only once they are of their
    kind (_wrong_kind), as it could not be made against a value of another:
    the key is not wrong yet, until those are refused."""
    kind = _wrong_kind(key, value)
    if kind:
        return kind
    keys = {field.name: field for field in fields(ReportSettings)}
    if any(_wrong_kind(keys[other], getattr(report_settings, other)) for other in key.metadata.get('reads', ())):
        return None
    if key.metadata.get('pattern'):
        if not value:
            return 'ACTIVITY_REPORTS[{!r}] is empty, which every title matches'.format(key.name)
        try:
            re.compile(value, re.IGNORECASE)
        except (re.error, OverflowError, RecursionError) as error:
            return 'ACTIVITY_REPORTS[{!r}] is not a pattern: {}'.format(key.name, error)
        unsafe = key.metadata['pattern'] == 'sql' and _sql_unsafe(value)
        if unsafe:
            return ('ACTIVITY_REPORTS[{!r}] has {}, which the database reads otherwise than Python, or refuses; '
                    'see _sql_unsafe'.format(key.name, unsafe))
    wrong = key.metadata.get('check') and key.metadata['check'](value, report_settings)
    return wrong and 'ACTIVITY_REPORTS[{!r}] {}: {!r}'.format(key.name, wrong, value)


def _of_type(value, kind):
    """Whether a value is of a key's type, its annotation: a float may be an
    int, a tuple's items are of its own type, and a bool is none of these."""
    if get_origin(kind) is tuple:
        return isinstance(value, tuple) and all(_of_type(item, get_args(kind)[0]) for item in value)
    return not isinstance(value, bool) and isinstance(value, (int, float) if kind is float else kind)


def _type_name(kind):
    return 'tuple of {}'.format(get_args(kind)[0].__name__) if get_origin(kind) is tuple else kind.__name__


def _read(setting):
    """What an ACTIVITY_REPORTS value gives: (the ReportSettings of its keys
    over the defaults, [a sentence for each thing refused]). A list given for
    a tuple is read as one. A key that is not one, or whose value is refused,
    keeps its default, as do all of them if the setting is not a dict; a
    value the team gave that leaves a default refused (RESPONDERS_THIN beyond
    RESPONDERS_FULL's), the team's own value of that key refused or not
    given, is refused in its place."""
    defaults = ReportSettings()
    if not isinstance(setting, dict):
        return defaults, ['ACTIVITY_REPORTS is a dict of the keys to change; every key keeps its default']
    keys = {key.name: key for key in fields(ReportSettings)}
    refused = []
    unknown = sorted(set(setting) - set(keys))
    if unknown:
        refused.append('ACTIVITY_REPORTS has no key {}; its keys are {}'.format(
            ', '.join(map(repr, unknown)), ', '.join(keys)))
    given = {name: tuple(value) if get_origin(keys[name].type) is tuple and isinstance(value, list) else value
             for name, value in setting.items() if name in keys}
    while True:
        values = SimpleNamespace(**{**{name: getattr(defaults, name) for name in keys}, **given})
        wrong = {name: _wrong(key, getattr(values, name), values) for name, key in keys.items()}
        wrong = {name: sentence for name, sentence in wrong.items() if sentence}
        if not wrong:
            return ReportSettings(**given), refused
        before = len(given)
        for name, sentence in wrong.items():
            if name in given:
                del given[name]
                refused.append(sentence + '; its default is used')
                continue
            # The default is refused: by a value it reads that the team gave, which is refused in its place.
            for other in keys[name].metadata.get('reads', ()):
                if other in given:
                    refused.append('ACTIVITY_REPORTS[{!r}] is refused, as with it {}; its default is used'.format(
                        other, sentence))
                    del given[other]
        if len(given) == before:        # a default refused whatever a team gives: a fault here, not theirs
            raise ImproperlyConfigured('ReportSettings refuses its own defaults: {}'.format(wrong))


@cache
def report_settings():
    """The activity reports' rules: ACTIVITY_REPORTS over the defaults, read
    once, and again when the setting changes (in a test), each key the
    check refuses (_read) keeping its default."""
    return _read(getattr(settings, 'ACTIVITY_REPORTS', {}))[0]


@receiver(setting_changed)
def _read_again(setting, **kwargs):
    if setting == 'ACTIVITY_REPORTS':
        report_settings.cache_clear()


@checks.register()
def check_report_settings(app_configs, **kwargs):
    """ACTIVITY_REPORTS as report_settings() reads it, at start-up: a warning
    for each key refused, naming it, which keeps its default. A warning, not
    an error, so that migrate and the task queue still start; the reports
    never read the refused value."""
    _, refused = _read(getattr(settings, 'ACTIVITY_REPORTS', {}))
    return [checks.Warning(sentence, id='main.W001') for sentence in refused]
