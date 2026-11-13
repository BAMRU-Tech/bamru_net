"""How the activity reports count logged time: days, events and hours,
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
- Hours go to the days they fell on; time on a day too short to count goes
  to the counted day beside it.
- Clock changes: hours are the time that passed, so the day the clocks
  change has 23 or 25 of them, and the 2-hour and 12-hour rules read
  elapsed hours. The 7-day limit is a calendar rule, so it reads the local
  clock: noon to noon seven days later is 7 days in any week of the year.
- Members are counted whatever their status today, alumni included, so that
  past years are not undercounted as people leave.
- Events count whether published or not: publishing puts an event on the
  calendars, and members see and log time on unpublished ones as well.
- AHC days are those a member did not also spend in the field, and OL days
  are operation days attended while flagged OL. The AHC flag means
  something only on operations, and an entry flagged both AHC and OL counts
  as AHC. An operation is attended as OL when flagged OL on any period of
  it, and as AHC when all the time on it was as AHC.
- Who led is entry_led's rule: a training (as TL or LL), a meeting or a
  community event when the event's leaders text names the member
  (Event.members_named, as the event page links a leader) or their entry is
  flagged OL; an operation when flagged OL in the field.
- An operation did not run once it has finished and no one in the field
  on it (so not the AHC), other than a guest, has a day attended on it up
  to today (operations_that_ran). That is read from the times logged; no
  cancellation is recorded, so one whose times are still to be entered has
  not run until they are. One that did not run was called off if a callout
  page was sent for it, or it started before pages carried reply templates,
  and was only a heads-up if not (heads_up_only, operations_not_run, which
  both reports use). A member listed without logged time on one
  called off stood down from it.
- DO weeks are assigned duty officer shifts that have started.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.db.models import BooleanField, Exists, ExpressionWrapper, F, OuterRef, Q
from django.template.defaultfilters import pluralize
from django.utils import timezone

from main.models import DoAvailable, Event, Member, Message, Participant

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

# How logged time becomes days; the glossary states them for readers.
DAY_HOURS = 2
SINGLE_DAY_HOURS = 12
MAX_ENTRY = timedelta(days=7)


# Events no report counts. Tests and demonstrations, by their title,
# ignoring case and a leading [tag]: "test", "test event", or one beginning
# "Demo Event". And operations never used: begun once pages were recorded
# (PAGES_FROM, the first), with no page sent and nobody listed, unless the
# title says "heads up", "heads-up" or "head's up": it may have gone by email.
TEST_TITLE = r"^\W*(\[[^]]*\]\s*)?(test(\s+event)?\W*$|demo\s+event)"
# Word edges written out, as \b means a backspace to Postgres.
HEADS_UP_TITLE = r"(^|\W)head(s|'s)[\s-]+up(\W|$)"
PAGES_FROM = date(2016, 8, 9)


def reported_events():
    """The events the reports count, all but those above, for every query
    that reads events or entries to count: a queryset of Event."""
    unused = (Q(type='operation', start_at__gte=timezone.make_aware(datetime.combine(PAGES_FROM, time.min)))
              & ~Exists(Message.objects.filter(format='page', period__event=OuterRef('pk')))
              & ~Exists(Participant.objects.filter(period__event=OuterRef('pk')))
              & ~Q(title__iregex=HEADS_UP_TITLE))
    return Event.objects.exclude(title__iregex=TEST_TITLE).exclude(unused)


# The same rule as Participant.timedelta > 0, for use in queries.
_EN_ROUTE_PAIR = Q(en_route_at__isnull=False, return_home_at__isnull=False)
HAS_TIME = (
    (_EN_ROUTE_PAIR & Q(return_home_at__gt=F('en_route_at'))) |
    (~_EN_ROUTE_PAIR & Q(signed_in_at__isnull=False, signed_out_at__isnull=False,
                         signed_out_at__gt=F('signed_in_at')))
)


# Time in the field: the AHC flag takes an entry out of it on operations only.
IN_FIELD = Q(ahc=False) | ~Q(period__event__type='operation')


def entry_led(event_type, ol, in_field, named):
    """Whether an entry led its event, for both reports: on an operation,
    flagged OL and in the field (IN_FIELD: so not one flagged AHC as well);
    on any other event, flagged OL or named in its leaders text."""
    return ol and in_field if event_type == 'operation' else ol or named


def logged_span(en_route_at, return_home_at, signed_in_at, signed_out_at):
    """An entry's logged time as (start, end): the travel times where both
    are given, otherwise the sign-in and sign-out times. None without time
    logged, the rule of HAS_TIME."""
    if en_route_at is not None and return_home_at is not None:
        start, end = en_route_at, return_home_at
    else:
        start, end = signed_in_at, signed_out_at
    if start is None or end is None or end <= start:
        return None
    return start, end


def too_long(start, end, tz=None):
    """Whether logged time from `start` to `end` runs more than MAX_ENTRY by
    the local clock, and so counts one day and no hours."""
    tz = tz or timezone.get_current_timezone()
    return end.astimezone(tz).replace(tzinfo=None) - start.astimezone(tz).replace(tzinfo=None) > MAX_ENTRY


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
    if sum(hours.values()) <= SINGLE_DAY_HOURS:
        return [fullest]
    return [day for day, h in hours.items() if h >= DAY_HOURS or day == fullest]


def _onto(days, hours):
    """{day: hours} for the counted days given: each day's hours on itself,
    or, for a day too short to count, on the counted day nearest it (the
    earlier of two as near), so that the hours add up as they fell."""
    if len(days) == 1:
        return {days[0]: sum(hours.values())}
    counted = {day: hours.get(day, 0) for day in days}
    for day, h in hours.items():
        if day not in counted:
            counted[min(counted, key=lambda other: abs((other - day).days))] += h
    return counted


def day_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, tz=None, claim=None):
    """{local calendar day: hours} for the days an entry's logged time
    counts for, oldest first. The hours are those that fell on each day; time
    on a day too short to count goes to the counted day beside it, so the
    hours add up to the entry's. Empty without time logged; the day it starts,
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


def entry_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, started, now, tz=None, claim=None):
    """{local day: hours} an entry counts for by `now`: its day_hours (of
    `claim`, as there) up to end_of_today, and none for an event that had
    not started by then."""
    tz = tz or timezone.get_current_timezone()
    if started > now:
        return {}
    stop = end_of_today(now, tz).date()
    return {day: hours for day, hours
            in day_hours(en_route_at, return_home_at, signed_in_at, signed_out_at, tz, claim).items() if day < stop}


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


def entries_hours(entries, now, tz=None):
    """For one member's entries, each (started, en_route_at, return_home_at,
    signed_in_at, signed_out_at), in member_entries' order so that every
    report breaks a tie alike, the hours each counts for by `now`, in that
    order: entry_hours, but with time the member logged twice (two
    periods or events at once) counted once, for the entry whose time began
    first (first_claims). An entry's days are its own, by the day rule over
    all its time; only its hours are the part it claims. An entry of an
    event not started, or too long to be right, claims no time; time after
    today claims it, though it counts nothing yet."""
    tz = tz or timezone.get_current_timezone()
    spans = {}
    for i, (started, *times) in enumerate(entries):
        span = logged_span(*times)
        if started <= now and span and not too_long(*span, tz):
            spans[i] = span
    claims = dict(zip(spans, first_claims(list(spans.values()))))
    return [entry_hours(*times, started, now, tz, claim=(claims[i] or ()) if i in claims else None)
            for i, (started, *times) in enumerate(entries)]


# The reply templates of the pages for an operation: a callout asks who can
# go; a heads-up warns that a callout may follow. Pages carry one from
# REPLY_TEMPLATES_FROM, the first that did; before it the two cannot be told apart.
CALLOUT = 'Available?'
HEADS_UP = 'Heads Up'
REPLY_TEMPLATES_FROM = date(2019, 2, 13)


def heads_up_only(started, until):
    """Of operations that finished without running, given with the local day
    each started ({id: day}), those the unit was only warned of, by the pages
    sent up to `until`: {ids}. From REPLY_TEMPLATES_FROM, one with no callout
    page, whether it had heads-up pages or none. Before that date pages cannot
    tell, and none is, not even one titled as a heads-up, which its title
    keeps in reporting (reported_events)."""
    told_apart = {event_id for event_id, day in started.items() if day >= REPLY_TEMPLATES_FROM}
    called_out = Message.objects.filter(format='page', created_at__lte=until, rsvp_template__name=CALLOUT,
                                        period__event__in=told_apart).values_list('period__event_id', flat=True)
    return told_apart - set(called_out)


@dataclass(frozen=True)
class NotRun:
    """Why an operation did not run, and when it would have."""
    why: str            # 'heads_up' (heads_up_only) or 'called_off'
    started: date       # the local day it started


def operations_not_run(until, ran, operations=None):
    """Each operation that had finished by `until` and is not among those
    that ran (`ran`, the set of their ids: operations_that_ran's, or the
    unit report's reading of the same rule), of all operations or of the
    ids given: {operation id: NotRun}."""
    if operations is not None and ran >= set(operations):
        return {}           # all of them ran: nothing more to look up
    finished = reported_events().filter(type='operation', finish_at__lte=until)
    if operations is not None:
        finished = finished.filter(id__in=operations)
    started = {event_id: timezone.localtime(start_at).date()
               for event_id, start_at in finished.values_list('id', 'start_at') if event_id not in ran}
    heads_up = heads_up_only(started, until)
    return {event_id: NotRun('heads_up' if event_id in heads_up else 'called_off', day)
            for event_id, day in started.items()}


def unit_days_and_events(entries):
    """The unit's active days and its events, for both reports, from the
    entries that make the unit active (in the field, not a guest's), each
    as (event id, type, the local day the event started, the hours it counts
    for: entry_hours): ({type: {days}}, {type: {event id: the day it
    started}}). An event counts once one of its entries has a day counted."""
    days, events = defaultdict(set), defaultdict(dict)
    for event_id, event_type, started, hours in entries:
        if hours:
            days[event_type].update(hours)
            events[event_type].setdefault(event_id, started)
    return days, events


def unit_since(since, until):
    """What the unit did from the day `since` on, up to `until`, for a
    member's report, read in one pass: unit_days_and_events, with the
    events that started from `since` on. Some days before `since` may be
    among the days."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(since, time.min))
    # An entry counts for at most MAX_ENTRY, so nothing that began earlier
    # than this can reach the day asked for.
    earliest = start - MAX_ENTRY - timedelta(days=1)
    rows = (Participant.objects
            .filter(HAS_TIME, IN_FIELD, period__event__in=reported_events())
            .filter(Q(en_route_at__gte=earliest) | Q(signed_in_at__gte=earliest) | Q(period__event__start_at__gte=start))
            .exclude(member__status__in=Member.GUESTS)
            .values_list('period__event_id', 'period__event__type', 'period__event__start_at',
                         'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at'))
    days, events = unit_days_and_events(
        (event_id, event_type, start_at.astimezone(tz).date(), entry_hours(*times, start_at, until, tz))
        for event_id, event_type, start_at, *times in rows)
    return days, {t: {event_id: day for event_id, day in events[t].items() if day >= since} for t in TYPES}


def operations_that_ran(until, operations=None):
    """The operations that ran: those started by `until`, or of the ids
    given, at which a member other than the AHC, and not a guest, has a day
    attended up to until's local day. One that has finished and is not
    among them was called off. {ids}"""
    tz = timezone.get_current_timezone()
    rows = (Participant.objects
            .filter(HAS_TIME, IN_FIELD, period__event__type='operation', period__event__in=reported_events())
            .exclude(member__status__in=Member.GUESTS))
    if operations is not None:
        rows = rows.filter(period__event_id__in=operations)
    return {event_id for event_id, *times, started in rows.values_list(
                'period__event_id', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at',
                'period__event__start_at')
            if entry_hours(*times, started, until, tz)}


def member_entries(member):
    """A member's entries for the events the reports count (reported_events),
    with their periods and events, in the order of the lists on the activity
    report: by event, then period. The events' long
    descriptions, which no page of them shows, are left unread."""
    return list(Participant.objects.filter(member=member, period__event__in=reported_events())
                .annotate(in_field=ExpressionWrapper(IN_FIELD, output_field=BooleanField()))
                .select_related('period__event')
                .defer('period__event__description', 'period__event__description_private')
                .order_by('period__event__start_at', 'period__event_id', 'period__position', 'id'))


@dataclass(frozen=True)
class Counted:
    """One of a member's entries with logged time, as the reports count it."""
    event: Event
    hours: dict         # {local day: hours} the time counts for by now (entry_hours)
    led: bool           # off operations: entry_led, when the caller asked for who led; else the OL flag only
    ol: bool            # on an operation: entry_led
    in_field: bool      # IN_FIELD: false only for time as AHC on an operation

    def hour_keys(self):
        """What its hours count towards: its type, and what it was done as,
        or 'other_' and its type when none of those: counted in their own
        right, not as the type's hours less the rest, which floating point
        can leave a hair below zero."""
        kind = self.event.type
        role = 'led_' + kind if self.led else 'ahc' if not self.in_field else 'ol' if self.ol else 'other_' + kind
        return [kind, role]


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
class Record:
    """A member's entries with logged time, as counted, in the order of
    member_entries; and the operations they were listed on without any."""
    entries: list       # [Counted]
    no_time: dict       # operations listed on with no time that counts: event id -> event

    def days(self, event_type, led=False):
        """{day: event} for the days attended at events of a type: in the
        field, for operations; only those led, with `led`. Of two entries on
        one day, the later gives the event."""
        return {day: entry.event for entry in self.entries
                if entry.event.type == event_type and entry.in_field and (entry.led or not led)
                for day in entry.hours}

    def ahc_days(self):
        """{day: operation} for the days on operations as AHC."""
        return {day: entry.event for entry in self.entries if not entry.in_field for day in entry.hours}

    def ol_days(self):
        return {day for entry in self.entries if entry.ol for day in entry.hours}

    def events(self):
        """{event id: Attended}, for the events attended."""
        by_event = defaultdict(list)
        for entry in self.entries:
            by_event[entry.event.id].append(entry)
        return {event_id: Attended(type=entries[0].event.type,
                                   day=timezone.localtime(entries[0].event.start_at).date(),
                                   led=any(e.led for e in entries), ol=any(e.ol for e in entries),
                                   in_field=any(e.in_field for e in entries))
                for event_id, entries in by_event.items()}


def _record(member, now, entries=None, leading=True):
    """A member's Record, from their entries (member_entries, loaded here
    unless given), each with the hours it counts for by `now` (entry_hours).
    Without `leading`, what they led by being named in an event's leaders
    text is not worked out, for a caller that does not read it."""
    entries = member_entries(member) if entries is None else entries
    # The members each leaders text names, read once for all the member's
    # events, by the rule the event page links leaders by.
    texts = {p.period.event.leaders for p in entries if p.period.event.type != 'operation'}
    named = Event.members_named(texts) if leading and any(texts) else {}
    counted, no_time, timed_operations = [], {}, set()
    entries = [p for p in entries if p.period.event.type in TYPES]      # the types the reports show
    hours_of = entries_hours([(p.period.event.start_at, p.en_route_at, p.return_home_at, p.signed_in_at,
                               p.signed_out_at) for p in entries], now)
    for p, hours_by_day in zip(entries, hours_of):
        event = p.period.event
        operation = event.type == 'operation'
        if not hours_by_day:
            if operation:
                no_time[event.id] = event
            continue
        if operation:
            timed_operations.add(event.id)
        led = entry_led(event.type, p.ol, p.in_field, member.id in named.get(event.leaders, ()))
        counted.append(Counted(event=event, hours=hours_by_day, led=led and not operation, ol=led and operation,
                               in_field=p.in_field))
    return Record(entries=counted,
                  no_time={event_id: event for event_id, event in no_time.items() if event_id not in timed_operations})


def count_entry_days(participants, now=None):
    """Set on each entry what the totals count of it, by the rules of the glossary:
    `days`, its counted days up to today; `counted_hours`, the hours on
    those days; and `left_out_hours`, the rest of its hours, which count
    towards no total (a mistake, or time for days still to come). Two
    entries on one day each show that day, though the totals count it once."""
    now = now or timezone.now()
    # The types the reports show, as the totals read them, so that time logged twice is the same entry's.
    shown = [p for p in participants if p.period.event.type in TYPES]
    hours_of = dict(zip(shown, entries_hours([(p.period.event.start_at, p.en_route_at, p.return_home_at,
                                               p.signed_in_at, p.signed_out_at) for p in shown], now)))
    for p in participants:
        counted = list(hours_of.get(p, {}).values())
        p.days = len(counted)
        # Rounded far past the tenth shown, so that an entry's days, added up,
        # show as its own hours do: 3.78 and 23.77 make 27.549999..., not 27.55.
        p.counted_hours = round(sum(counted), 6)
        p.left_out_hours = round(p.hours - sum(counted), 6)      # from the sum before rounding: nothing, when nothing is


def _ago(then, today):
    """How long ago, in whole months, or whole years from two years on."""
    months = (today.year - then.year) * 12 + today.month - then.month
    if today.day < then.day:
        months -= 1
    if months < 1:
        return 'Under a month'
    if months < 24:
        return '{} month{}'.format(months, pluralize(months))
    return '{} years'.format(months // 12)


def member_latest(member, now=None):
    """The last day the member attended an event of each type, for the member
    page, with the event. For operations that is a day in the field; a later
    day as AHC, and a later operation they stood down from (by the day it
    started), are added as lines of their own. Returns [] when there is
    nothing to show, which includes a member only listed on an operation
    still under way: it is not called off until it has finished."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    record = _record(member, now, leading=False)      # who led is not shown here
    # Operations the member was listed on without time that have finished, so
    # perhaps called off: usually none, and then the unit is not asked. A
    # member stands down from an operation called off, not one that was
    # only a heads-up.
    candidates = [event for event in record.no_time.values() if event.finish_at <= now]
    ids = [event.id for event in candidates]
    not_run = operations_not_run(now, operations_that_ran(now, ids), ids) if candidates else {}
    called_off = {not_run[event.id].started: event
                  for event in candidates if event.id in not_run and not_run[event.id].why == 'called_off'}

    def last(days_to_events, after=()):
        """The most recent of these days, with its event, if it is later
        than every day in `after`; or {}."""
        day = max(days_to_events, default=None)
        if day is None or any(other and other >= day for other in after):
            return {}
        return {'day': day, 'event': days_to_events[day], 'ago': _ago(day, today)}

    # AHC duty and standing down are not time in the field, so each is shown
    # only when it is more recent than the lines above it.
    in_field = last(record.days('operation'))
    as_ahc = last(record.ahc_days(), after=[in_field.get('day')])
    stood_down = last(called_off, after=[in_field.get('day'), as_ahc.get('day')])
    one = dict(Event.TYPES)         # the name of one event of each type
    latest = ([{'label': one['operation'] + ' (in the field)', **in_field}]
              + [{'label': label, **line} for label, line in ((one['operation'] + ' (as AHC)', as_ahc),
                                                              (one['operation'] + ' (stood down)', stood_down)) if line]
              + [{'label': one[t], **last(record.days(t))} for t in TYPES[1:]])
    return latest if any('event' in item for item in latest) else []


def _do_days(member, now):
    """The days the member's assigned duty officer shifts started, up to now."""
    local_now = timezone.localtime(now).replace(tzinfo=None)    # shifts start at a local time
    return {start.date() for start in (
        DoAvailable.shift_start(year, quarter, week)
        for year, quarter, week in DoAvailable.objects.filter(member=member, assigned=True)
                                                      .values_list('year', 'quarter', 'week'))
        if start <= local_now}


def _each(f, figures):
    """`f` applied to each figure in a nest of plain dicts of them. A figure
    may be a Counter, which is a dict too, so the test is for dict itself."""
    return {k: _each(f, v) for k, v in figures.items()} if type(figures) is dict else f(figures)


def activity_rows(member, now=None, entries=None):
    """Count a member's days, duties and hours by year and by month, from the
    first day they were involved to today (or to the last day, for someone no
    longer a member): {'years': [rows], 'months': [rows], 'total': row},
    each row a period's figures with its 'year', or its 'month' as (year,
    month). Returns None when there is nothing to count."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    do_days = _do_days(member, now)
    record = _record(member, now, entries)

    # Days as AHC are days attended on operations, apart from days in the field.
    days = {t: set(record.days(t)) for t in TYPES}
    ahc_days = set(record.ahc_days()) - days['operation']
    days['operation'] |= ahc_days
    any_days = set().union(*days.values())
    events = record.events()
    involved = any_days | do_days | {e.day for e in events.values()}
    if not involved:
        return None
    first = min(involved)
    last = today if member.status in Member.CURRENT_MEMBERS else max(involved)
    # The unit's days matter only from the member's first day on.
    active, unit = unit_since(first, now)
    # A day the member attended is a unit active day for them, as AHC when
    # nobody went out or as a guest among guests; and an event they attended
    # is a unit event.
    active = {t: active[t] | days[t] for t in TYPES}
    unit = {t: {**unit[t], **{event_id: e.day for event_id, e in events.items() if e.type == t}} for t in TYPES}
    # Across all types a day counts once, under the first type in the order
    # above that the member attended on it.
    first_days, counted = {}, set()
    for t in TYPES:
        first_days[t] = days[t] - counted
        counted |= days[t]

    def started(keep):
        """The day each event kept by `keep` started: events count once, on that day."""
        return [e.day for e in events.values() if keep(e)]

    # Each figure a row shows, as the days it counts: a set of days counts
    # each day once, a list of days each event on the day it started.
    figures = {
        'days': days,
        'active_days': active,
        'led_days': {t: set(record.days(t, led=True)) for t in TYPES},
        'first_days': first_days,
        'all_days': any_days,
        'all_active_days': set().union(*active.values()),
        'duty': {'ol': record.ol_days(), 'ahc': ahc_days, 'do': do_days},
        'events': {t: started(lambda e, t=t: e.type == t) for t in TYPES},
        'unit_events': {t: list(unit[t].values()) for t in TYPES},
        'led_events': {t: started(lambda e, t=t: e.type == t and e.led) for t in TYPES},
        'event_duty': {'ol': started(lambda e: e.ol),
                       'ahc': started(lambda e: e.type == 'operation' and not e.in_field)},
    }
    # Count everything by month once; a year is the sum of its months.
    monthly = _each(lambda days: Counter((day.year, day.month) for day in days if first <= day <= last), figures)
    monthly_hours = defaultdict(float)       # the member's own days, all from first to last
    for entry in record.entries:
        for day, hours in entry.hours.items():
            for key in entry.hour_keys():
                monthly_hours[(day.year, day.month, key)] += hours

    def row(months):
        """Add up the months given, each a (year, month)."""
        hours = {k: sum(monthly_hours[(y, m, k)] for y, m in months)
                 for k in TYPES + ['led_' + t for t in TYPES] + ['other_' + t for t in TYPES] + ['ol', 'ahc']}
        return {**_each(lambda counts: sum(counts[m] for m in months), monthly),
                'hours': hours, 'all_hours': sum(hours[t] for t in TYPES)}

    all_months = [(y, m) for y in range(first.year, last.year + 1) for m in range(1, 13)
                  if (first.year, first.month) <= (y, m) <= (last.year, last.month)]
    return {
        'years': [{'year': y, **row([(y, m) for m in range(1, 13)])} for y in range(first.year, last.year + 1)],
        'months': [{'month': (y, m), **row([(y, m)])} for y, m in all_months],
        'total': row(all_months),
    }
