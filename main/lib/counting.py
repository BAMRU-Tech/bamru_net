"""How the activity reports count logged time: days, events, OPs and hours,
for one member and for the unit.

The rules are stated once, for readers, in main.lib.activity.glossary():
what a day attended is, a unit active day, an event attended, a unit event,
hours, and what is left out. The functions here apply them. What the
glossary leaves to the code:
- An entry is one member's row on one operating period of an event (a
  Participant). Its time is the travel times where both are given, otherwise
  the sign-in and sign-out times.
- Today is the local day. A day after it counts nothing yet, for days,
  events and hours alike, for a member and for the unit: it is a slip in
  the times entered, or time still to come.
- An event counts once one of its counted days has come, and is placed on
  the local day it started, whichever days of it were attended.
- OPs are an event's operating periods (Period), dated by op_days; ANY_TIME
  is the time that attends one.
- An entry's hours are shown on the days attended it counts as, each on the
  date it fell on; hours on another of its dates go to the nearest of those
  days (the earlier of two as near), so none are lost.
- Clock changes: hours are the time that passed, so the day the clocks
  change has 23 or 25 of them, and the 2-hour and 12-hour rules read
  elapsed hours. The 7-day limit is a calendar rule, so it reads the local
  clock: noon to noon seven days later is 7 days in any week of the year.
- Members are counted whatever their status today, alumni included, so that
  past years are not undercounted as people leave, and from the day they
  joined (joined_on), so that a member's joining adds nothing to the unit's
  past.
- Events count whether published or not: publishing puts an event on the
  calendars, and members see and log time on unpublished ones as well.
- AHC days are those a member did not also spend in the field, and OL days
  are operation days attended while flagged OL. The AHC flag means
  something only on operations, and an entry flagged both AHC and OL counts
  as AHC. An operation is attended as OL when flagged OL on any period of
  it, and as AHC when all the time on it was as AHC.
- Who led is entry_led's rule: a training (as TL or LL), a meeting or a
  community event when the event's leaders text names the member
  (members_named, as the event page links a leader) or their entry is
  flagged OL; an operation when flagged OL in the field.
- An operation did not run once it has finished and no one in the field on
  it (so not the AHC), other than a guest, has a day attended on it up to
  today, or a departure logged (operations_that_ran, departure_entries).
  That is read from the times logged; no cancellation is recorded, so one
  whose times are still to be entered has not run until they are. One that
  did not run was only a heads-up if no callout page was sent for it, or,
  begun before pages carried reply templates and so could tell, if its title
  says it was a heads-up; it was called off if not (heads_up_only,
  operations_not_run, which both reports use). A member listed without
  logged time on one called off stood down from it.
- DO weeks are assigned duty officer shifts that have started.
"""
import calendar
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import ClassVar, NamedTuple
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.db.models import (BooleanField, Case, Exists, ExpressionWrapper, F, Min, OuterRef, Q, Subquery, Value,
                              When)
from django.db.models.functions import Coalesce, ExtractYear, TruncDate
from django.template.defaultfilters import pluralize
from django.utils import timezone

from main.lib.report_settings import report_settings
from main.models import Cert, DoAvailable, Event, Member, Message, Participant, Period
from main.models.event import every_username, members_named

# In the order they are shown.
EVENT_TYPES = (
    ('operation', 'Operations'),
    ('training', 'Trainings'),
    ('meeting', 'Meetings'),
    ('community', 'Community'),
)
TYPES = [event_type for event_type, _ in EVENT_TYPES]

# What leading each type of event is called (entry_led says who led).
LEADING = {'operation': 'OL', 'training': 'TL or LL', 'meeting': 'leader', 'community': 'leader'}

def pages():
    """The pages the reports read, for both, as a queryset of Message: those
    sent from the event page but its Test button's, which pages the sender
    alone to try paging out (period_format 'test')."""
    return Message.objects.filter(format='page').exclude(period_format='test')


def _first_operation_page():
    """The local day of the first page (pages) sent for an operation, but
    for a test or demonstration's (TEST_TITLE), which may have tried paging
    out first, as a one-row queryset: pages for operations were recorded
    from that day."""
    return (pages().filter(period__event__type='operation')
            .exclude(period__event__title__iregex=report_settings().TEST_TITLE)
            .order_by('created_at').annotate(day=TruncDate('created_at')).values('day')[:1])


def pages_from():
    """The local day pages for operations were first recorded, from which an
    operation with no page sent and nobody listed was never used
    (reported_events); None before any. One query, for a report's text."""
    first = _first_operation_page().first()
    return first and first['day']


def reported_events(since=None):
    """The events the reports count, for every query that reads events or
    entries to count: those of the types they show (TYPES), but for tests and
    demonstrations, by their title (TEST_TITLE), operations never used, and
    those begun outside EARLIEST to LATEST: a queryset of Event. With `since`
    (records_from), only those begun from that day: one dated earlier counts
    nowhere."""
    rules = report_settings()
    # Pages for operations were recorded from the local day of the first, which the database finds once for
    # each query that reads this. An operation begun from then with no page sent and nobody listed was never
    # used, unless its title says it was a heads-up (HEADS_UP_TITLE), which may have gone by email. With no
    # page recorded yet, no operation is begun after one, so none is left out as never used.
    paged_from = Coalesce(Subquery(_first_operation_page()), Value(date.max))
    unused = (Q(type='operation', start_day__gte=paged_from)
              & ~Exists(pages().filter(period__event=OuterRef('pk')))
              & ~Exists(Participant.objects.filter(period__event=OuterRef('pk')))
              & ~Q(title__iregex=rules.HEADS_UP_TITLE))
    events = (Event.objects.filter(type__in=TYPES, start_at__gte=EARLIEST, start_at__lte=LATEST)
              .alias(start_day=TruncDate('start_at'))
              .exclude(title__iregex=rules.TEST_TITLE).exclude(unused))
    return events if since is None else events.filter(start_at__gte=local_midnight(since))


def local_midnight(day, tz=None):
    """The local midnight that begins `day`."""
    return timezone.make_aware(datetime.combine(day, time.min), tz or timezone.get_current_timezone())


# The same rule as Participant.timedelta > 0, for use in queries.
_EN_ROUTE_PAIR = Q(en_route_at__isnull=False, return_home_at__isnull=False)
HAS_TIME = (
    (_EN_ROUTE_PAIR & Q(return_home_at__gt=F('en_route_at'))) |
    (~_EN_ROUTE_PAIR & Q(signed_in_at__isnull=False, signed_out_at__isnull=False,
                         signed_out_at__gt=F('signed_in_at')))
)


# Time in the field: the AHC flag takes an entry out of it on operations only.
IN_FIELD = Q(ahc=False) | ~Q(period__event__type='operation')
# Any time logged on an entry, even one time alone: what attends an OP.
ANY_TIME = (Q(en_route_at__isnull=False) | Q(return_home_at__isnull=False) | Q(signed_in_at__isnull=False)
            | Q(signed_out_at__isnull=False))


def entry_led(event_type, ol, in_field, named):
    """Whether an entry led its event, for both reports: on an operation,
    flagged OL and in the field (IN_FIELD: so not one flagged AHC as well);
    on any other event, flagged OL or named in its leaders text."""
    return ol and in_field if event_type == 'operation' else ol or named


# The first moment that has a local date in every time zone: an event begun
# earlier counts nowhere, and time logged earlier is no time, as a date typed
# into year 1 can be read in none of them.
EARLIEST = datetime(1, 1, 2, tzinfo=dt_timezone.utc)
# And the last whose local day ends, in every time zone, at a midnight a date
# can hold: an event begun later counts nowhere, and time logged later is no
# time, as a day of 31 December 9999 cannot be counted to its end.
LATEST = datetime(9999, 12, 30, tzinfo=dt_timezone.utc)


def logged_span(en_route_at, return_home_at, signed_in_at, signed_out_at):
    """An entry's logged time as (start, end): the travel times where both
    are given, otherwise the sign-in and sign-out times. None without time
    logged, the rule of HAS_TIME, or outside EARLIEST to LATEST."""
    if en_route_at is not None and return_home_at is not None:
        start, end = en_route_at, return_home_at
    else:
        start, end = signed_in_at, signed_out_at
    if start is None or end is None or end <= start or start < EARLIEST or end > LATEST:
        return None
    return start, end


def too_long(start, end, tz=None):
    """Whether logged time from `start` to `end` runs more than MAX_ENTRY_DAYS
    by the local clock, and so counts one day and no hours."""
    tz = tz or timezone.get_current_timezone()
    limit = timedelta(days=report_settings().MAX_ENTRY_DAYS)
    return end.astimezone(tz).replace(tzinfo=None) - start.astimezone(tz).replace(tzinfo=None) > limit


def hours_by_local_day(start, end, tz=None):
    """{local calendar day: hours}, oldest first, of the time from `start`
    to `end` that fell on each day. Hours are the time that passed, so the
    day the clocks change has 23 or 25 of them."""
    tz = tz or timezone.get_current_timezone()
    start, end = start.astimezone(tz), end.astimezone(tz)
    hours = {}
    for n in range((end.date() - start.date()).days + 1):
        day = start.date() + timedelta(days=n)
        midnight = start.replace(year=day.year, month=day.month, day=day.day,
                                 hour=0, minute=0, second=0, microsecond=0)
        next_midnight = midnight + timedelta(days=1)
        # Subtract in UTC: local times an hour apart on the clock are not always an hour apart.
        on_day = (min(end, next_midnight).astimezone(dt_timezone.utc) -
                  max(start, midnight).astimezone(dt_timezone.utc))
        if on_day:
            hours[day] = on_day.total_seconds() / 3600
    return hours


def _counted_days(hours):
    """The days of an entry's time, {local day: hours} as it fell, that the
    day rule counts, oldest first: the fullest alone for 12 hours or less,
    otherwise every day with 2 hours or more, and the fullest."""
    fullest = max(hours, key=hours.get)
    rules = report_settings()
    if sum(hours.values()) <= rules.SINGLE_DAY_HOURS:
        return [fullest]
    return [day for day, h in hours.items() if h >= rules.DAY_HOURS or day == fullest]


def _onto(days, hours):
    """{day: hours} for the counted days given: each day's hours on itself,
    or, for a day too short to count, on the counted day nearest it (the
    earlier of two as near), so that the hours add up as they fell."""
    if len(days) == 1:
        return {days[0]: sum(hours.values())}
    placed = {day: hours.get(day, 0) for day in days}
    for day, h in hours.items():
        if day not in placed:
            placed[min(placed, key=lambda other: abs((other - day).days))] += h
    return placed


def day_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, tz=None, claim=None):
    """{local calendar day: hours} for the days an entry's logged time
    counts for, oldest first. The hours are those that fell on each day; those
    on another of the entry's dates go to the nearest day it counts for
    (_onto), so the hours add up to the entry's. Empty without time logged; the day it starts,
    with no hours, when the entry is too long to be right. `claim` is the
    part of the time the entry keeps where its member logged time twice, as
    (start, end), or () for none (first_claims, for entries_hours): the days
    are still those of all its time, and the hours those of the claim. `tz`
    is the local timezone, for a caller with many entries to look it up once."""
    tz = tz or timezone.get_current_timezone()
    span = logged_span(en_route_at, return_home_at, signed_in_at, signed_out_at)
    if span is None:
        return {}
    start, end = span
    if too_long(start, end, tz):
        return {start.astimezone(tz).date(): 0}
    hours = hours_by_local_day(start, end, tz)
    claimed = hours if claim is None or claim == span else hours_by_local_day(*claim, tz) if claim else {}
    return _onto(_counted_days(hours), claimed)


def end_of_today(now, tz=None):
    """The local midnight that ends now's day, where counting stops: time
    after it, and the days after today, count nothing yet. It is a slip in
    the times entered, or time still to come."""
    tz = tz or timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(now.astimezone(tz).date() + timedelta(days=1), time.min), tz)


def entry_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, start_at, now, tz=None, claim=None):
    """{local day: hours} an entry counts for by `now`: its day_hours (of
    `claim`, as there) up to end_of_today, and none when its event starts,
    at `start_at`, after now. The days are those of all its time, and the
    hours those it logged by end_of_today, where the unit report's hours
    stop too: time after it counts nothing yet, though it may decide which
    day counts."""
    tz = tz or timezone.get_current_timezone()
    if start_at > now:
        return {}
    stops = end_of_today(now, tz)
    claim = logged_span(en_route_at, return_home_at, signed_in_at, signed_out_at) if claim is None else claim
    if claim and claim[1] > stops:
        claim = (claim[0], stops) if claim[0] < stops else ()
    return {day: hours for day, hours
            in day_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, tz, claim).items()
            if day < stops.date()}


def first_claims(spans):
    """Time logged twice counts once, for the span that began first: for
    each (start, end), in the order given, the part of it that no span which
    began earlier (or as early, and is given before it) covers, as (start,
    end), or None when it is covered. Together the parts are the spans'
    union, each moment once."""
    claims, reached = [None] * len(spans), None
    for i, (start, end) in sorted(enumerate(spans), key=lambda item: (item[1][0], item[0])):
        begin = start if reached is None else max(start, reached)
        if end > begin:
            claims[i] = (begin, end)
        reached = end if reached is None else max(reached, end)
    return claims


def entries_hours(entries, now, tz=None, since=None):
    """For one member's entries, each (start_at, en_route_at, return_home_at,
    signed_in_at, signed_out_at), in member_entries' order so that every
    report breaks a tie alike, the hours each counts for by `now`, in that
    order: entry_hours, but with time the member logged twice (two
    periods or events at once) counted once, for the entry whose time began
    first (first_claims). An entry's days are its own, by the day rule over
    all its time; only its hours are the part it claims. An entry of an
    event not started, or too long to be right, claims no time; time after
    today claims it, though it counts nothing yet. Counted from `since`
    (records_from) on: days before it count nothing, and an entry of an
    event begun before it counts nowhere and claims no time, None in its
    place."""
    tz = tz or timezone.get_current_timezone()
    counts, claims = _claims(entries, now, tz, since)
    hours = []
    for i, (start_at, *times) in enumerate(entries):
        claim = (claims[i] or ()) if i in claims else None
        hours.append(_counted_from(entry_hours(*times, start_at, now, tz, claim), since) if counts[i] else None)
    return hours


def _claims(entries, now, tz, since):
    """For entries_hours' entries, whether each counts at all (its event
    begun on or after `since`), and {index: claim} for those that claim
    time (first_claims), each claim (start, end) or None when other time
    covers it all."""
    begins = since and local_midnight(since, tz)
    counts = [not begins or start_at >= begins for start_at, *_ in entries]
    spans = {}
    for i, (start_at, *times) in enumerate(entries):
        span = logged_span(*times)
        if counts[i] and start_at <= now and span and not too_long(*span, tz):
            spans[i] = span
    return counts, dict(zip(spans, first_claims(list(spans.values()))))


def _counted_from(hours, since):
    """An entry's {day: hours} from the day `since` (records_from) on: the
    days before it count nothing. All of them when `since` is None."""
    return hours if since is None else {day: h for day, h in hours.items() if day >= since}


# The order of a member's entries that every report reads them in (entries_hours), so that all break a tie alike.
ENTRY_ORDER = ('period__event__start_at', 'period__event_id', 'period__position', 'id')


class UnitTime(NamedTuple):
    """An entry's time, for the unit's figures (unit_time)."""
    counted: dict               # {local day: hours} it counts for by now (entries_hours), joined then or not
    hours: dict                 # those on days its member had joined: the unit's
    span: tuple                 # the (start, end) logged, up to the end of today, from the first of those days when
                                #   days before it are left out; None without them, or when too long to be right


def unit_time(entries, now, since, joining=None, tz=None):
    """The time of these entries for the unit, a UnitTime each, in the order
    given: entries of events the reports count from `since` (records_from),
    each (member, start_at, en_route_at, return_home_at, signed_in_at,
    signed_out_at, …), anything after those the caller's, and each member's
    in ENTRY_ORDER. Time on a day before its member joined (Joining) is a
    guest's, and left out; with no `joining`, none is."""
    tz = tz or timezone.get_current_timezone()
    entries = list(entries)
    by_member = defaultdict(list)        # member -> the indexes of their entries, in the order given
    for i, (member, *_) in enumerate(entries):
        by_member[member].append(i)
    counted = {}
    for indexes in by_member.values():
        counted.update(zip(indexes, entries_hours([entries[i][1:6] for i in indexes], now, tz, since)))
    stops = end_of_today(now, tz)
    times = []
    for i, (member, _, *logged) in enumerate(entries):
        hours = counted[i] or {}
        kept = hours if joining is None else {day: h for day, h in hours.items() if joining.member_on(member, day)}
        span = logged_span(*logged[:4]) if kept else None
        if span:
            start, end = span
            span = None if too_long(start, end, tz) else (start, min(end, stops))
        if span and len(kept) < len(hours):
            span = (max(span[0], local_midnight(min(kept), tz)), span[1])
        times.append(UnitTime(hours, kept, span))
    return times


def reply_templates_from():
    """The local day of the first page for an operation the reports count
    (reported_events) that said whether it was a callout or a heads-up, by its
    reply template (CALLOUT_TEMPLATE or HEADS_UP_TEMPLATE): from it an
    operation's pages tell the two apart; before it they cannot. None when no
    page has said. One query, which a report makes once."""
    rules = report_settings()
    first = (pages().filter(period__event__in=reported_events().filter(type='operation'),
                            rsvp_template__name__in=(rules.CALLOUT_TEMPLATE, rules.HEADS_UP_TEMPLATE))
             .aggregate(first=Min('created_at'))['first'])
    return first and timezone.localtime(first).date()


def heads_up_only(started, titled, until, templates_from):
    """Of operations that finished without running, given with the local day
    each started ({id: day}), those the unit was only warned of: {ids}. From
    `templates_from` (reply_templates_from), when an operation's pages say
    which they are, one with no callout page sent by `until`, whatever its
    title, whether it had heads-up pages or none. Before that day, or with
    none, when pages cannot tell, one whose title says it was a heads-up
    (`titled`, their ids: HEADS_UP_TITLE). The rest were called off."""
    told_apart = {event_id for event_id, day in started.items() if templates_from and day >= templates_from}
    called_out = pages().filter(created_at__lte=until, rsvp_template__name=report_settings().CALLOUT_TEMPLATE,
                                period__event__in=told_apart).values_list('period__event_id', flat=True)
    return (told_apart - set(called_out)) | (titled - told_apart)


@dataclass(frozen=True)
class NotRun:
    """Why an operation did not run, and when it would have."""
    CALLED_OFF: ClassVar[str] = 'called_off'        # called out, then called off
    HEADS_UP_ONLY: ClassVar[str] = 'heads_up'       # only ever a heads-up (heads_up_only)

    why: str            # CALLED_OFF or HEADS_UP_ONLY
    started: date       # the local day it started


def has_finished(start_at, finish_at, until):
    """Whether an operation had finished by `until`: its start and its finish
    are both past, so that one saved finishing before it starts has not
    finished until it has started."""
    return max(start_at, finish_at) <= until


def operations_not_run(until, ran, templates_from, operations=None):
    """Each operation that had finished by `until` (has_finished) and is not among those
    that ran (`ran`, the set of their ids: operations_that_ran's, or the
    unit report's reading of the same rule), of all operations or of the
    ids given: {operation id: NotRun}. `templates_from` is
    reply_templates_from(), which the report reads once."""
    candidates = (reported_events().filter(type='operation')
                  .annotate(titled=ExpressionWrapper(Q(title__iregex=report_settings().HEADS_UP_TITLE),
                                                     output_field=BooleanField())))
    if operations is not None:
        candidates = candidates.filter(id__in=operations)
    started, titled = {}, set()
    for event_id, start_at, finish_at, says_heads_up in candidates.values_list('id', 'start_at', 'finish_at', 'titled'):
        if event_id not in ran and has_finished(start_at, finish_at, until):
            started[event_id] = timezone.localtime(start_at).date()
            if says_heads_up:
                titled.add(event_id)
    heads_up = heads_up_only(started, titled, until, templates_from)
    return {event_id: NotRun(NotRun.HEADS_UP_ONLY if event_id in heads_up else NotRun.CALLED_OFF, day)
            for event_id, day in started.items()}


def first_year(years):
    """The year a series starts: the earliest of `years` (those with data) that
    no run of STRAY_BEFORE or more empty years separates from the latest, so
    that a stray early record, such as a mistyped year, does not start it."""
    stray_before = report_settings().STRAY_BEFORE
    first = max(years)
    for year in sorted(years, reverse=True):
        if first - year > stray_before:
            break
        first = year
    return first


def records_from(now):
    """The first day both reports count from: 1 January of the unit's first
    year (first_year) of those in which a report counts something by `now`:
    an event it counts (reported_events) begun that year on which a member,
    not a guest, has a day attended (entry_hours) from then on; an operation
    it counts that has finished, which the unit report counts as run, called
    off or a heads-up; or the day a duty officer week counts on
    (_do_shift_days). So a date mistyped long before the rest (0024 for
    2024) counts on neither report, and what neither counts, a week assigned
    for years ahead or time typed into a year long gone among them, moves
    nothing. None with no records. One query, which a report makes once, and
    a second for a year whose only time is in doubt (_years_counted)."""
    timed = Participant.objects.filter(HAS_TIME, period__event=OuterRef('pk')).exclude(member__status__in=Member.GUESTS)
    # Time that began in its event's year or later and was all logged by the end of today surely counts a day
    # of that year or later, the fullest or, for time too long to be right, its first: no later than today.
    # Other time may count none (_years_counted).
    # The year is read only of a time from EARLIEST to LATEST, which has a local date in every time zone, as
    # SQLite's cannot be read of one without; time outside them is no time (logged_span).
    began = Case(When(_EN_ROUTE_PAIR, then=F('en_route_at')), default=F('signed_in_at'))
    ended = Case(When(_EN_ROUTE_PAIR, then=F('return_home_at')), default=F('signed_out_at'))
    sure = (timed.alias(began_at=began, ended=ended)
            .alias(began=Case(When(began_at__gte=EARLIEST, began_at__lte=LATEST, then=ExtractYear('began_at')),
                              default=Value(0)))
            .filter(began__gte=OuterRef('year'), ended__lte=end_of_today(now)))
    counted = Q(type='operation', finish_at__lte=now) | Q(Exists(sure))
    # The events' years, each as (year, 0, 0), or (year, -1, 0) where its time is in doubt, and the shifts, each
    # (year, quarter, week), in one query.
    rows = (reported_events().filter(start_at__lte=now)
            .filter(Q(Exists(timed)) | Q(type='operation', finish_at__lte=now))
            .annotate(year=ExtractYear('start_at'))
            .annotate(quarter=Case(When(counted, then=Value(0)), default=Value(-1)), week=Value(0))
            .values_list('year', 'quarter', 'week')
            .union(_shifts(DoAvailable.objects.filter(assigned=True), now)))
    years, in_doubt, shifts = set(), set(), []
    for year, quarter, week in rows:
        if quarter > 0:         # a shift's is 1 to 4 (_shifts)
            shifts.append((year, quarter, week))
        else:
            (years if quarter == 0 else in_doubt).add(year)
    if in_doubt - years:
        years |= _years_counted(in_doubt - years, now)
    years |= {day.year for day in _do_shift_days(shifts, now)}
    return date(first_year(years), 1, 1) if years else None


def _years_counted(years, now):
    """Of these years, those in which an event the reports count began by
    `now` that has a member's day attended (entry_hours), not a guest's,
    from 1 January of that year on, for records_from. {years}"""
    tz = timezone.get_current_timezone()
    # Only events begun in those years: from the first's start (EARLIEST in year 1, as its local midnight may
    # fall before any date east of Greenwich) to the last's end, or to now.
    first = local_midnight(date(min(years), 1, 1), tz) if min(years) > EARLIEST.year else EARLIEST
    last = local_midnight(date(max(years) + 1, 1, 1), tz) if max(years) < date.max.year else now
    begun = reported_events().filter(start_at__gte=first, start_at__lt=last, start_at__lte=now)
    entries = (Participant.objects.filter(HAS_TIME, period__event__in=begun).exclude(member__status__in=Member.GUESTS)
               .values_list('period__event__start_at', 'en_route_at', 'return_home_at', 'signed_in_at',
                            'signed_out_at'))
    counted = set()
    for start_at, *times in entries:
        year = start_at.astimezone(tz).year
        if year in years and year not in counted and any(day.year >= year
                                                         for day in entry_hours(*times, start_at, now, tz)):
            counted.add(year)
    return counted


# The year of an endorsement with no date: its comment starts with the year, or with "by" and the year, as in
# "2008 (from the residency sheet)" or "by 2006 (background check 2006)", which is only the latest it can be.
COMMENT_YEAR = re.compile(r'(by\s+)?(\d{4})(?!\d)', re.IGNORECASE)


def endorsements(today):
    """The day each member, not a guest, first earned each endorsement the
    reports read, up to today, and which of those days are only the latest it
    can be: ({(member, endorsement): day}, {(member, endorsement)}). One with
    no date counts from the first of January of its comment's year
    (COMMENT_YEAR), a bound after "by", and without that is left out."""
    rules = report_settings()
    earliest = {}                        # (member, endorsement) -> (day, whether only a bound)
    for member, name, earned, comment in (
            Cert.objects.filter(Q(earned_on__lte=today) | Q(earned_on__isnull=True),
                                subtype__type__name=rules.ENDORSEMENTS,
                                subtype__name__in={rules.JOINED_ENDORSEMENT, *rules.PROMOTIONS, *rules.BANDED_STATUSES})
            .exclude(member__status__in=Member.GUESTS)
            .values_list('member_id', 'subtype__name', 'earned_on', 'comment')):
        bound = False
        if earned is None:
            year = COMMENT_YEAR.match((comment or '').strip())
            if not (year and 1 <= int(year[2]) <= today.year):
                continue
            earned, bound = date(int(year[2]), 1, 1), bool(year[1])
        earliest[(member, name)] = min((earned, bound), earliest.get((member, name), (earned, bound)))
    return ({key: day for key, (day, _) in earliest.items()}, {key for key, (_, bound) in earliest.items() if bound})


class Joining(NamedTuple):
    """The day each member joined (joined_on)."""
    on: dict                    # member -> the day they joined
    by: set                     # those whose day is only the latest it can be: a "by" year, or their first
                                #   training or operation

    def member_on(self, member, day):
        """Whether the member had joined by this day: their time on it is a
        member's, for the unit, and not a guest's."""
        return day >= self.on.get(member, date.max)


def joined_on(now, since, endorsed=None):
    """Joining: each member's day of joining, that of their joining
    endorsement (report_settings' JOINED_ENDORSEMENT), or without one, their
    first day at a training or an operation the reports count from `since`
    (records_from) by `now`, only the latest it can be. A member with neither
    has not joined."""
    tz = timezone.get_current_timezone()
    joining = report_settings().JOINED_ENDORSEMENT
    days, bounds = endorsed or endorsements(now.astimezone(tz).date())
    on = {member: day for (member, name), day in days.items() if name == joining}
    first = {}                           # member without the endorsement -> their first day at a training or operation
    rows = list(Participant.objects.filter(HAS_TIME, period__event__in=reported_events(since).filter(
                    type__in=('training', 'operation')))
                .exclude(member__status__in=Member.GUESTS).exclude(member_id__in=list(on)).order_by(*ENTRY_ORDER)
                .values_list('member_id', 'period__event__start_at', 'en_route_at', 'return_home_at', 'signed_in_at',
                             'signed_out_at'))
    for (member_id, *_), time in zip(rows, unit_time(rows, now, since, tz=tz)):
        if time.counted:
            first[member_id] = min(min(time.counted), first.get(member_id, date.max))
    return Joining({**on, **first}, {member for member, name in bounds if name == joining} | set(first))


def unit_days_and_events(entries):
    """The unit's active days and its events, for both reports, from the
    entries that make the unit active (in the field, a member's), each
    as (event id, type, the local day the event started, the hours it counts
    for: entry_hours): ({type: {days}}, {type: {event id: the day it
    started}}). An event counts once one of its entries has a day counted."""
    days, events = defaultdict(set), defaultdict(dict)
    for event_id, event_type, started, hours in entries:
        if hours:
            days[event_type].update(hours)
            events[event_type].setdefault(event_id, started)
    return days, events


def op_days(events, now):
    """{period id: the day its OP stands for}, for the periods of these events
    (ids, or a queryset of Event) whose OPs count by `now`: their event has
    begun and their day has come. In their order on the event page, then as
    created, the first OP is the local day the event started and each next
    one the day after."""
    tz = timezone.get_current_timezone()
    today = now.astimezone(tz).date()
    by_event = defaultdict(list)
    for period_id, event_id, position, start_at in (Period.objects.filter(event__in=events, event__start_at__lte=now)
                                                    .values_list('id', 'event_id', 'position', 'event__start_at')):
        by_event[event_id].append((position is None, position or 0, period_id, start_at))
    days = {}
    for periods in by_event.values():
        periods.sort()
        first = periods[0][3].astimezone(tz).date()
        for k, (_, _, period_id, _) in enumerate(periods[:(today - first).days + 1]):
            days[period_id] = first + timedelta(days=k)
    return days


class UnitOp(NamedTuple):
    """One member's attendance of one OP."""
    period: int
    type: str
    day: date                   # the day the OP stands for
    member: int
    in_field: bool              # IN_FIELD, on any of their entries on it

    @property
    def responder(self):
        return self.type == 'operation' and self.in_field


def unit_ops(now, since, joining):
    """The OPs members attended, as UnitOp records, one for each member and
    OP: those counting by `now` (op_days), of events begun from `since`
    (records_from), from the day they joined (Joining). Guests' are left
    out."""
    events = reported_events(since)
    on_day = op_days(events, now)
    attended = {}                        # (member, period) -> UnitOp
    for period_id, event_type, member_id, in_field in (
            Participant.objects.filter(ANY_TIME, period__event__in=events).exclude(member__status__in=Member.GUESTS)
            .annotate(in_field=ExpressionWrapper(IN_FIELD, output_field=BooleanField()))
            .values_list('period_id', 'period__event__type', 'member_id', 'in_field')):
        if period_id in on_day and joining.member_on(member_id, on_day[period_id]):
            was = attended.get((member_id, period_id))
            attended[(member_id, period_id)] = UnitOp(period_id, event_type, on_day[period_id], member_id,
                                                      in_field or bool(was and was.in_field))
    return list(attended.values())


class UnitSince(NamedTuple):
    """What the unit did, for a member's report (unit_since)."""
    days: dict                  # {type: {unit active days}}
    events: dict                # {type: {unit event id: the day it started}}
    ops: dict                   # {type: {the days of its unit OPs}}


def unit_since(first, until, since):
    """What the unit did from the day `first` on, up to `until`, for a
    member's report, read in one pass: unit_days_and_events, counted from
    `since` (records_from) on, each member's from the day they joined
    (joined_on), and the days of its unit OPs. Some days before `first`, and
    events and OPs before it, may be among them, for the caller to count
    from `first` on. A UnitSince."""
    tz = timezone.get_current_timezone()
    start = local_midnight(first, tz)
    # An entry counts for at most MAX_ENTRY_DAYS, so nothing that began earlier
    # than this can reach the day asked for.
    reach = timedelta(days=report_settings().MAX_ENTRY_DAYS + 1)
    earliest = start - reach if start - EARLIEST > reach else EARLIEST
    rows = list(Participant.objects
                .filter(HAS_TIME, IN_FIELD, period__event__in=reported_events(since))
                .filter(Q(en_route_at__gte=earliest) | Q(signed_in_at__gte=earliest)
                        | Q(period__event__start_at__gte=start))
                .exclude(member__status__in=Member.GUESTS).order_by(*ENTRY_ORDER)
                .values_list('member_id', 'period__event__start_at', 'en_route_at', 'return_home_at', 'signed_in_at',
                             'signed_out_at', 'period__event_id', 'period__event__type'))
    joining = joined_on(until, since)
    days, events = unit_days_and_events(
        (event_id, event_type, start_at.astimezone(tz).date(), time.hours)
        for (_, start_at, *_, event_id, event_type), time in zip(rows, unit_time(rows, until, since, joining, tz)))
    ops = defaultdict(set)
    for op in unit_ops(until, since, joining):
        if op.in_field:
            ops[op.type].add(op.day)
    return UnitSince(days, events, ops)


class Departure(NamedTuple):
    """An entry that logs a departure for an operation (departure_entries)."""
    operation: int
    member: int
    ol: bool
    operation_start: datetime
    left_at: datetime


def departure_entries(until, since, joining, operations=None):
    """The entries that log a departure for an operation by `until`, as
    Departure records: on operations begun by then that the reports count
    from `since` (records_from) on, or of the ids given, by members in the
    field (not the AHC), not guests, who had joined by the day they left
    (Joining), with a departure (Left) logged by the end of until's day,
    whatever else of their times is logged yet, as the reply to a "Left?"
    page logs only that. A departure means the operation ran, though it
    counts no day or hours until the time is complete."""
    tz = timezone.get_current_timezone()
    rows = (Participant.objects
            .filter(IN_FIELD, period__event__type='operation', en_route_at__lt=end_of_today(until),
                    period__event__in=reported_events(since).filter(start_at__lte=until))
            .exclude(member__status__in=Member.GUESTS))
    if operations is not None:
        rows = rows.filter(period__event_id__in=operations)
    departed = (Departure(*row) for row in rows.values_list('period__event_id', 'member_id', 'ol',
                                                            'period__event__start_at', 'en_route_at'))
    return [left for left in departed if joining.member_on(left.member, left.left_at.astimezone(tz).date())]


def operations_that_ran(until, operations, since):
    """Those of these operations, by id, that ran by `until`: at which a
    member other than the AHC, and not a guest, has a day attended up to
    until's local day, counted from `since` (records_from) on and from the
    day they joined (joined_on), as the unit report counts its responders,
    or has left for it (departure_entries). One that has finished and is not
    among them was called off. {ids}"""
    if not operations:
        return set()
    tz = timezone.get_current_timezone()
    joining = joined_on(until, since)
    rows = list(Participant.objects
                .filter(HAS_TIME, IN_FIELD, period__event__type='operation', period__event__in=reported_events(since),
                        period__event_id__in=operations)
                .exclude(member__status__in=Member.GUESTS).order_by(*ENTRY_ORDER)
                .values_list('member_id', 'period__event__start_at', 'en_route_at', 'return_home_at', 'signed_in_at',
                             'signed_out_at', 'period__event_id'))
    ran = {row[-1] for row, time in zip(rows, unit_time(rows, until, since, joining, tz)) if time.hours}
    # Those with a day attended ran: the rest are asked whether anyone left for them, usually none.
    rest = set(operations) - ran
    return ran | {left.operation for left in departure_entries(until, since, joining, rest)} if rest else ran


def member_entries(member):
    """A member's entries for the events the reports count (reported_events),
    with their periods and events, in the order of the lists on the activity
    report: by event, then period. The events' long
    descriptions, which no page of them shows, are left unread."""
    return list(Participant.objects.filter(member=member, period__event__in=reported_events())
                .annotate(in_field=ExpressionWrapper(IN_FIELD, output_field=BooleanField()),
                          any_time=ExpressionWrapper(ANY_TIME, output_field=BooleanField()))
                .select_related('period__event')
                .defer('period__event__description', 'period__event__description_private')
                .order_by(*ENTRY_ORDER))


@dataclass(frozen=True)
class CountedEntry:
    """One of a member's entries with logged time, as the reports count it."""
    event: Event
    hours: dict         # {local day: hours} the time counts for by now (entry_hours)
    led: bool           # off operations: entry_led, when the caller asked for who led; else the OL flag only
    ol: bool            # on an operation: entry_led
    in_field: bool      # IN_FIELD: false only for time as AHC on an operation

    def hours_towards(self):
        """The ActivityRow figures its hours count towards, each (field, its
        type, or None for a figure of every type): its type's hours, and
        what it was done as, or other_hours when none of those: counted in
        their own right, not as the type's hours less the rest, which
        floating point can leave a hair below zero."""
        kind = self.event.type
        role = (('led_hours', kind) if self.led else ('ahc_hours', None) if not self.in_field
                else ('ol_hours', None) if self.ol else ('other_hours', kind))
        return [('hours', kind), role]


@dataclass(frozen=True)
class Attended:
    """An event a member attended, as it counts: once, on the local day it
    started, however many of its days or periods they attended."""
    type: str
    day: date
    led: bool           # on any of the member's entries for it
    ol: bool
    in_field: bool      # on any of them; for an operation, false when all the time on it was as AHC


@dataclass(frozen=True)
class AttendedOp:
    """An OP a member attended."""
    type: str
    day: date           # the day it stands for
    led: bool           # off operations: entry_led, on any of the member's entries for it
    ol: bool            # on an operation: entry_led, on any of them
    in_field: bool      # on any of them


@dataclass(frozen=True)
class MemberRecord:
    """A member's entries with logged time, as counted, in the order of
    member_entries; the operations they were listed on without any; and the
    OPs they attended, when asked for."""
    counted: list       # [CountedEntry]
    no_time: dict       # operations listed on with no time that counts: event id -> event
    ops: dict           # period id -> AttendedOp

    def days(self, event_type, led=False):
        """{day: event} for the days attended at events of a type: in the
        field, for operations; only those led, with `led`. Of two entries on
        one day, the later gives the event."""
        return {day: entry.event for entry in self.counted
                if entry.event.type == event_type and entry.in_field and (entry.led or not led)
                for day in entry.hours}

    def ahc_days(self):
        """{day: operation} for the days on operations as AHC."""
        return {day: entry.event for entry in self.counted if not entry.in_field for day in entry.hours}

    def ol_days(self):
        """{day: operation} for the days in the field as OL (entry_led). Of
        two entries on one day, the later gives the operation."""
        return {day: entry.event for entry in self.counted if entry.ol for day in entry.hours}

    def events(self):
        """{event id: Attended}, for the events attended."""
        by_event = defaultdict(list)
        for entry in self.counted:
            by_event[entry.event.id].append(entry)
        return {event_id: Attended(type=entries[0].event.type,
                                   day=timezone.localtime(entries[0].event.start_at).date(),
                                   led=any(e.led for e in entries), ol=any(e.ol for e in entries),
                                   in_field=any(e.in_field for e in entries))
                for event_id, entries in by_event.items()}


def _times(entries):
    """A member's entries (member_entries) as entries_hours takes them."""
    return [(p.period.event.start_at, p.en_route_at, p.return_home_at, p.signed_in_at, p.signed_out_at)
            for p in entries]


def counted_hours(entries, now, since):
    """The hours each of a member's entries (member_entries) counts for by
    `now`, from `since` (records_from) on, in their order: entries_hours.
    A page that shows both the lists and the totals works it out once."""
    return entries_hours(_times(entries), now, since=since)


def _record(member, now, since, entries=None, leading=TYPES, hours=None, ops=False):
    """A member's MemberRecord, from their entries (member_entries, loaded here
    unless given), each with the hours it counts for by `now` (counted_hours,
    worked out here unless given) from `since` (records_from) on. What they
    led by being named in an event's leaders text is worked out for the
    types in `leading`; the OPs they attended are worked out with `ops`."""
    entries = member_entries(member) if entries is None else entries
    # The members each leaders text names, read once for all the member's
    # events, by the rule the event page links leaders by.
    texts = {p.period.event.leaders for p in entries
             if p.period.event.type in leading and p.period.event.type != 'operation'}
    named = members_named(texts, every_username()) if any(texts) else {}
    on_day = op_days({p.period.event_id for p in entries}, now) if ops else {}
    counted, no_time, timed_operations, attended_ops = [], {}, set(), {}
    for p, hours_by_day in zip(entries, counted_hours(entries, now, since) if hours is None else hours):
        event = p.period.event
        if hours_by_day is None:
            continue            # begun before the unit's records: counted nowhere, not even as stood down from
        operation = event.type == 'operation'
        led = entry_led(event.type, p.ol, p.in_field, member.id in named.get(event.leaders, ()))
        if p.any_time and p.period_id in on_day:
            was = attended_ops.get(p.period_id)
            attended_ops[p.period_id] = AttendedOp(
                type=event.type, day=on_day[p.period_id], led=(led and not operation) or bool(was and was.led),
                ol=(led and operation) or bool(was and was.ol), in_field=p.in_field or bool(was and was.in_field))
        if not hours_by_day:
            if operation:
                no_time[event.id] = event
            continue
        if operation:
            timed_operations.add(event.id)
        counted.append(CountedEntry(event=event, hours=hours_by_day, led=led and not operation,
                                    ol=led and operation, in_field=p.in_field))
    return MemberRecord(counted=counted,
                        no_time={event_id: event for event_id, event in no_time.items()
                                 if event_id not in timed_operations},
                        ops=attended_ops)


@dataclass(frozen=True)
class ListedEntry:
    """One of a member's entries as their report lists it, with what the
    totals count of it, by the rules of the glossary. Its hours are
    counted_hours + elsewhere_hours + left_out_hours; its counted days up to
    today are days + elsewhere_days, so that a type's list, its days added
    up, has the type's days in the totals."""
    entry: Participant
    days: int               # its counted days up to today that no other entry of its type keeps
    elsewhere_days: int     # those another entry of its type, whose time began first, keeps
    counted_hours: float    # the hours on all its counted days
    elsewhere_hours: float  # the hours another of the member's entries covers, and counts (first_claims)
    left_out_hours: float   # the rest, which no entry counts: a mistake, or days still to come
    # Time with no logged span (logged_span), such as one that ends before it starts, is none: all three are 0.


def _length(span):
    """The hours from start to end of a span, (start, end), or of None: 0."""
    return (span[1] - span[0]).total_seconds() / 3600 if span else 0


def listed_entries(entries, now, since, hours=None):
    """A member's entries (member_entries) as their report lists them, by
    `now`, counted from `since` (records_from) on as the totals are, with
    the hours each counts for (counted_hours, worked out here unless given):
    [ListedEntry], in the order given. Of an entry's hours that it does not
    count, those that another entry's time covers count for that entry
    (first_claims), or will once the day they count on has come; the rest,
    its own, count for none. A day two entries of one type count is kept by
    the one whose time began first (or as early, and is given first), as
    time logged twice is."""
    tz = timezone.get_current_timezone()
    _, claims = _claims(_times(entries), now, tz, since)
    hours = counted_hours(entries, now, since) if hours is None else hours
    spans = [logged_span(p.en_route_at, p.return_home_at, p.signed_in_at, p.signed_out_at) for p in entries]
    # Every entry with a counted day has logged time: the first of each type to begin keeps each of its days.
    keeps = {}
    for i in sorted((i for i, by_day in enumerate(hours) if by_day), key=lambda i: (spans[i][0], i)):
        for day in hours[i]:
            keeps.setdefault((entries[i].period.event.type, day), i)
    listed = []
    for i, (p, by_day, span) in enumerate(zip(entries, hours, spans)):
        on_days = list((by_day or {}).values())
        own = sum(1 for day in by_day or {} if keeps[(p.period.event.type, day)] == i)
        elsewhere = _length(span) - _length(claims[i]) if i in claims else 0
        # Rounded far past the tenth shown, so that an entry's days, added up,
        # show as its own hours do: 3.78 and 23.77 make 27.549999..., not 27.55.
        listed.append(ListedEntry(entry=p, days=own, elsewhere_days=len(on_days) - own,
                                  counted_hours=round(sum(on_days), 6),
                                  elsewhere_hours=round(elsewhere, 6),
                                  # from the sums before rounding: nothing, when nothing is
                                  left_out_hours=round(p.hours - sum(on_days) - elsewhere, 6) if span else 0))
    return listed


def months_after(day, months):
    """The day `months` calendar months after `day`, or the last of its month
    where that month is shorter (29 February to 28 February), for both
    reports."""
    year, month = divmod(day.month - 1 + months, 12)
    year, month = day.year + year, month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def whole_months(since, until):
    """The whole calendar months from one day to another (months_after), as
    an age counts them."""
    months = (until.year - since.year) * 12 + until.month - since.month
    return months - 1 if months_after(since, months) > until else months


def _ago(then, today):
    """How long ago, to the nearest calendar month (whole_months), or the
    nearest year from two years on, a half rounding up."""
    months = whole_months(then, today)
    start, end = months_after(then, months), months_after(then, months + 1)
    months += (today - start).days / (end - start).days
    if months < 0.5:
        return 'Under a month'
    if months < 23.5:
        return '{} month{}'.format(int(months + 0.5), pluralize(int(months + 0.5)))
    return '{} years'.format(int(months / 12 + 0.5))


_READ = object()     # member_latest's `since` when not given: it reads records_from itself


def member_latest(member, now=None, since=_READ):
    """The last day the member attended an event of each type, for the member
    page, with the event. For operations that is a day in the field; the last
    day in the field as OL, whenever they have been OL, even the same day; and
    a later day as AHC, and a later operation they stood down from (by the day
    it started), are added as lines of their own. Trainings likewise: the last
    as a participant, in any role, and the last they led (as TL or LL),
    whenever they have led one. Returns [] when there is
    nothing to show, which includes a member only listed on an operation
    still under way: it is not called off until it has finished. `since`
    is records_from(now), read here unless given, or as the page keeps it,
    for a now up to report_cache.EXPIRY before (report_cache.records_from)."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    since = records_from(now) if since is _READ else since
    record = _record(member, now, since, leading=('training',))
    # Operations the member was listed on without time that have finished, so
    # perhaps called off: usually none, and then the unit is not asked. A
    # member stands down from an operation called off, not one that was
    # only a heads-up. Before OPERATION_TIMES_FROM most operations have
    # nobody's times, so whether one ran is not known (the unit report
    # greys it), and none of them is said to have been stood down from.
    times_from = report_settings().OPERATION_TIMES_FROM
    candidates = [event for event in record.no_time.values() if has_finished(event.start_at, event.finish_at, now)
                  and timezone.localtime(event.start_at).year >= times_from]
    ids = [event.id for event in candidates]
    ran = operations_that_ran(now, ids, since)
    not_run = operations_not_run(now, ran, reply_templates_from(), ids) if set(ids) - ran else {}
    called_off = {not_run[event.id].started: event
                  for event in candidates if event.id in not_run and not_run[event.id].why == NotRun.CALLED_OFF}

    def last(days_to_events, after=()):
        """The most recent of these days, with its event, if it is later
        than every day in `after`; or {}."""
        day = max(days_to_events, default=None)
        if day is None or any(other and other >= day for other in after):
            return {}
        return {'day': day, 'event': days_to_events[day], 'ago': _ago(day, today)}

    # AHC duty and standing down are not time in the field, so each is shown
    # only when it is more recent than the lines above it. A day as OL is a
    # day in the field, so never later than that line: it is shown whenever
    # there is one, so that the table says when the member last led.
    in_field = last(record.days('operation'))
    as_ol = last(record.ol_days())
    as_ahc = last(record.ahc_days(), after=[in_field.get('day')])
    stood_down = last(called_off, after=[in_field.get('day'), as_ahc.get('day')])
    led_training = last(record.days('training', led=True))
    one = dict(Event.TYPES)         # the name of one event of each type
    latest = ([{'label': one['operation'] + ' (in the field)', **in_field}]
              + [{'label': label, **line} for label, line in ((one['operation'] + ' (as OL)', as_ol),
                                                              (one['operation'] + ' (as AHC)', as_ahc),
                                                              (one['operation'] + ' (stood down)', stood_down)) if line]
              + [{'label': one['training'] + ' (as participant)', **last(record.days('training'))}]
              + ([{'label': '{} (as {})'.format(one['training'], LEADING['training']), **led_training}]
                 if led_training else [])
              + [{'label': one[t], **last(record.days(t))} for t in TYPES[2:]])
    return latest if any('event' in item for item in latest) else []


def _shifts(assigned, now):
    """Of these duty officer shifts (DoAvailable), the real weeks that may
    have begun by now, as (year, quarter, week): of quarters 1 to 4 and weeks
    1 to 14 (_do_shift_days reads which quarters have a 14th), in a year whose
    first shift a date can hold, so not year 1, which began in the year before.
    A DO year begins in the last week of the year before at the earliest, so
    no later one has a shift begun. The DO schedule's API and the admin check
    none of this."""
    return (assigned.filter(year__gt=EARLIEST.year, year__lte=timezone.localtime(now).year + 1,
                            quarter__range=(1, 4), week__range=(1, 14))
            .values_list('year', 'quarter', 'week'))


def _do_shift_days(shifts, now):
    """The day each of these duty officer shifts, (year, quarter, week),
    counts on, for those begun by now: its fourth, so that a week split
    across two months or years counts in the one that holds most of its seven
    days, or today, for a shift begun less than three days ago. A week 14 of a
    quarter with 13 is the next quarter's first again, and counts nothing. {days}"""
    local_now = timezone.localtime(now).replace(tzinfo=None)    # shifts start at a local time
    return {min(start + timedelta(days=3), local_now).date()
            for start in (DoAvailable.shift_start(year, quarter, week) for year, quarter, week in shifts
                          if week <= DoAvailable.num_weeks_in_quarter(year, quarter))
            if start <= local_now}


def _do_days(member, now):
    """The days the member's assigned duty officer shifts count on (_do_shift_days)."""
    return _do_shift_days(_shifts(DoAvailable.objects.filter(member=member, assigned=True), now), now)


@dataclass(frozen=True)
class ActivityRow:
    """A period's figures on a member's report: `period` is its year, its
    (year, month), or None for the whole. Each {type: n} has every type in
    TYPES. A day counts once, whatever was done on it; an event once, in the
    period it started."""
    period: object
    days: dict              # {type: days attended}; for operations, in the field or as AHC
    active_days: dict       # {type: unit active days}
    led_days: dict          # {type: days attended leading it}
    first_days: dict        # {type: the days attended that count under it, the first type in TYPES on each}
    events: dict            # {type: events attended}
    unit_events: dict       # {type: unit events}
    led_events: dict        # {type: events led}
    ops: dict               # {type: OPs attended}; for operations, in the field or as AHC
    unit_ops: dict          # {type: unit OPs}
    led_ops: dict           # {type: OPs attended leading it}
    first_ops: dict         # {type: the OPs that count under it, the first type in TYPES on each day}
    hours: dict             # {type: hours}
    led_hours: dict         # {type: hours leading it}
    other_hours: dict       # {type: hours neither leading nor, on operations, as OL or AHC}
    all_days: int           # days attended, each once
    all_active_days: int
    ol_days: int
    ahc_days: int
    do_days: int            # DO weeks
    ol_events: int
    ahc_events: int
    all_ops: int            # OPs attended, of every type, each day once
    all_unit_ops: int
    ol_ops: int
    ahc_ops: int
    ol_hours: float
    ahc_hours: float
    all_hours: float


def _started(events, keep):
    """{event id: the day it started} for the events, {id: Attended}, kept by `keep`."""
    return {event_id: e.day for event_id, e in events.items() if keep(e)}


def _by_month(days, first, last):
    """How many of these days fall in each month from `first` to `last`:
    Counter((year, month))."""
    return Counter((day.year, day.month) for day in days if first <= day <= last)


def _hours_by_month(record):
    """A member's hours, {(year, month, field, type or None): hours}, for each
    ActivityRow figure they count towards (CountedEntry.hours_towards)."""
    hours_by_month = defaultdict(float)
    for entry in record.counted:
        for day, hours in entry.hours.items():
            for field, kind in entry.hours_towards():
                hours_by_month[(day.year, day.month, field, kind)] += hours
    return hours_by_month


def _row(months, period, by_type, alone, hours_by_month):
    """The ActivityRow for these months, each a (year, month), adding up each
    figure's counts by month, {figure: {type: Counter}} (`by_type`) and
    {figure: Counter} (`alone`), and the hours (_hours_by_month)."""
    def total(counts):
        return sum(counts[m] for m in months)

    def hours(field, kind=None):
        return sum(hours_by_month[(y, m, field, kind)] for y, m in months)
    of_type = {field: {t: hours(field, t) for t in TYPES} for field in ('hours', 'led_hours', 'other_hours')}
    return ActivityRow(period=period,
                       **{name: {t: total(counts[t]) for t in TYPES} for name, counts in by_type.items()},
                       **{name: total(counts) for name, counts in alone.items()},
                       **of_type, ol_hours=hours('ol_hours'), ahc_hours=hours('ahc_hours'),
                       all_hours=sum(of_type['hours'][t] for t in TYPES))


def _under_first_type(by_type):
    """{type: days} with each day only under the first type in TYPES that has it."""
    under, earlier = {}, set()
    for t in TYPES:
        under[t] = by_type[t] - earlier
        earlier |= by_type[t]
    return under


def activity_rows(member, now, entries, since, hours=None, unit=None):
    """Count a member's days, duties and hours by year and by month, from the
    first day they were involved to today (or to the last day, for someone no
    longer a member), from their entries (member_entries), counting nothing
    before `since` (records_from), with the hours each entry counts for
    (counted_hours, worked out here unless given), and what the unit did
    (unit_since, read here unless given: unit_since(day, now, since) for some
    day no later than the member's first, and the same since and now, or a now
    up to report_cache.EXPIRY before it, as the report keeps it,
    report_cache.member_report; the member's own days and events are added to
    the unit's, so the unit's figure is never below theirs; or a function that
    gives it, called only for a member with something to count, and read here
    if it gives None): {'years': [ActivityRow],
    'months': [ActivityRow], 'total': ActivityRow}, oldest first. Returns
    None when there is nothing to count."""
    today = timezone.localtime(now).date()
    do_days = {day for day in _do_days(member, now) if since is None or day >= since}
    record = _record(member, now, since, entries, hours=hours, ops=True)

    # Days as AHC are days attended on operations, apart from days in the field.
    days = {t: set(record.days(t)) for t in TYPES}
    ahc_days = set(record.ahc_days()) - days['operation']
    days['operation'] |= ahc_days
    any_days = set().union(*days.values())
    events = record.events()
    # Sets of days, so that OPs of different events on one day are one, as days are.
    attended_ops = record.ops.values()
    ops = {t: {op.day for op in attended_ops if op.type == t} for t in TYPES}
    ahc_ops = ({op.day for op in attended_ops if op.type == 'operation' and not op.in_field}
               - {op.day for op in attended_ops if op.type == 'operation' and op.in_field})
    all_ops = set().union(*ops.values())
    involved = any_days | do_days | {e.day for e in events.values()} | all_ops
    if not involved:
        return None
    first = min(involved)
    last = today if member.status in Member.CURRENT_MEMBERS else max(involved)
    # The unit's days matter only from the member's first day on; any before it are not counted.
    active, unit, unit_op_days = (unit() if callable(unit) else unit) or unit_since(first, now, since)
    # A day the member attended is a unit active day for them, as AHC when
    # nobody went out or as a guest among guests; an event they attended is
    # a unit event, and an OP a unit OP.
    active = {t: active[t] | days[t] for t in TYPES}
    unit = {t: {**unit[t], **_started(events, lambda e, t=t: e.type == t)} for t in TYPES}
    unit_op_days = {t: unit_op_days[t] | ops[t] for t in TYPES}
    first_days, first_ops = _under_first_type(days), _under_first_type(ops)

    # Each figure counted by month: days as a set of them, so each counts
    # once, and events as {event id: the day it started}, so each counts
    # once on that day, however many share it. A year is the sum of its months.
    by_type = {
        **{name: {t: _by_month(of_type[t], first, last) for t in TYPES}
           for name, of_type in (('days', days), ('active_days', active),
                                 ('led_days', {t: set(record.days(t, led=True)) for t in TYPES}),
                                 ('first_days', first_days), ('ops', ops), ('unit_ops', unit_op_days),
                                 ('led_ops', {t: {op.day for op in attended_ops if op.type == t and op.led}
                                              for t in TYPES}),
                                 ('first_ops', first_ops))},
        **{name: {t: _by_month(of_type[t].values(), first, last) for t in TYPES}
           for name, of_type in (('events', {t: _started(events, lambda e, t=t: e.type == t) for t in TYPES}),
                                 ('unit_events', unit),
                                 ('led_events', {t: _started(events, lambda e, t=t: e.type == t and e.led)
                                                 for t in TYPES}))},
    }
    alone = {
        **{name: _by_month(days_of, first, last) for name, days_of in (
            ('all_days', any_days), ('all_active_days', set().union(*active.values())),
            ('ol_days', record.ol_days()), ('ahc_days', ahc_days), ('do_days', do_days),
            ('all_ops', all_ops), ('all_unit_ops', set().union(*unit_op_days.values())),
            ('ol_ops', {op.day for op in attended_ops if op.ol}), ('ahc_ops', ahc_ops))},
        **{name: _by_month(events_of.values(), first, last) for name, events_of in (
            ('ol_events', _started(events, lambda e: e.ol)),
            ('ahc_events', _started(events, lambda e: e.type == 'operation' and not e.in_field)))},
    }
    hours_by_month = _hours_by_month(record)
    all_months = [(y, m) for y in range(first.year, last.year + 1) for m in range(1, 13)
                  if (first.year, first.month) <= (y, m) <= (last.year, last.month)]
    return {
        'years': [_row([(y, m) for m in range(1, 13)], y, by_type, alone, hours_by_month)
                  for y in range(first.year, last.year + 1)],
        'months': [_row([(y, m)], (y, m), by_type, alone, hours_by_month) for y, m in all_months],
        'total': _row(all_months, None, by_type, alone, hours_by_month),
    }
