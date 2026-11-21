"""What the unit activity report counts, read from the database: the entries
it reads (unit_entries), the counts made of them, and unit_rows, which puts them
in rows by year for main.lib.unit_activity to draw. The terms are defined in
the report's glossary; this says what the code decides beyond them.

- The rules a member's report shares come from main.lib.counting: the days
  and hours an entry counts for the unit (unit_time), unit active days and
  unit events (unit_days_and_events), heads-ups (heads_up_only) and the
  events reported (reported_events). Which operations ran is operations_that_ran's rule, read
  from this report's own entries rather than asked again.
- Days are weekdays or weekend days by their own dates, whatever day their
  event started; an event and an operation belong to the local day they
  started, and an OP to the day it stands for (counting.op_days). OPs are
  read apart from the time that counts days (unit_ops), as one time logged
  attends one. Member-hours go with the days they count for, so hours either
  side of midnight can sit on the neighbouring day; unit active hours sit
  on the calendar days the time fell on.
- A responder's status on a day is the latest recorded on or before it; for
  a member whose own history starts later, their first recorded status.
  Before the earliest record (status_from), from report_settings'
  OPERATION_TIMES_FROM, it is that of their latest endorsement of a banded
  status, or Other without one, when any member has such an endorsement;
  days before then are left out of the split.
- An operation's first page is the earliest page sent for any of its
  periods. A repage goes to those who have not replied, and a reply to it
  is marked on every page before it, so a page and its repages count once
  for each member: from the first of them they were sent to their first
  reply, yes or no, in the year and hour that first page went out.
- An immediate callout's clock runs to the first en-route time logged at or
  after its first such page: a responder already out did not leave in
  answer to it.
- Every figure here counts a member from the day they joined
  (counting.joined_on). Becoming inactive is read from activity (LEFT_AFTER
  and REPORTABLE).
"""
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import NamedTuple

from django.db.models import BooleanField, ExpressionWrapper, F, Min, Q, Window
from django.db.models.functions import Lag
from django.utils import timezone

from main.lib.counting import (ENTRY_ORDER, HAS_TIME, IN_FIELD, TYPES, NotRun, departure_entries, endorsements,
                               entry_led, first_claims, hours_by_local_day, joined_on, months_after,
                               operations_not_run, pages, records_from, reply_templates_from, reported_events,
                               unit_days_and_events, unit_ops, unit_time, whole_months)
from main.lib.report_settings import report_settings
from main.models import Distribution, Member, Participant, Unavailable
from main.models.event import every_username, members_named


class Cuts(tuple):
    """Named categories of an amount, smallest first, as (name, the most it
    holds); the last holds the rest, its most None."""

    @property
    def names(self):
        return tuple(name for name, _ in self)

    def name_for(self, amount):
        """The first category whose most the amount does not pass."""
        return next(name for name, most in self if most is None or amount <= most)


# The categories the report counts in: what each count is split by, and the names the rows give them.
SIZES = ('thin', 'middling', 'full')     # how many responders: report_settings' RESPONDERS_THIN and _FULL
NOT_RUN = (NotRun.CALLED_OFF, NotRun.HEADS_UP_ONLY)   # why an operation nobody went on did not run
OUTCOMES = SIZES + NOT_RUN
PARTS_OF_WEEK = Cuts((('weekday', 4), ('weekend', None)))       # by date.weekday(): Monday 0 to Friday 4
OTHER_STATUS = 'other'                   # a status without a band of its own (report_settings' BANDED_STATUSES)
# A stretch in the field: of one day, of one long day (report_settings' LONG_DAY), of two days, or more.
RUN_LENGTHS = ('day', 'long_day', 'two', 'more')
REPLY_SPEEDS = ('minutes', 'hour', 'later')     # how soon a reply came: by report_settings' REPLY_MINUTES
REPLY_KINDS = REPLY_SPEEDS + ('untimed', 'none')                # then a reply with no time, and none
DEPARTURE_SPEEDS = ('half', 'hour', 'later')    # how soon the first responder left: by DEPARTURE_MINUTES
DEPARTURE_KINDS = DEPARTURE_SPEEDS + ('none',)                  # then no departure logged after the page
FLOW_KINDS = ('joined', 'came_back', 'left', 'left_returned')
ROLES = ('others', 'led')                # who attended an event: those who did not lead it, and those who did
WHOSE = ('unit', 'people')               # whose days, events and hours: the unit's (any member out), its members'
MEASURES = ('ops', 'days', 'events', 'hours')   # what participation is counted in

# What keeps a member active; report_settings' LEFT_AFTER says for how long without it they have left.
REPORTABLE = ('operation', 'training', 'community')


def _named_leaders(rows):
    """{event: the ids of the members its leaders text names}, for the events
    of the entry rows given that are not operations, by the rule the event
    page links them by. Each distinct text is read once."""
    texts = {event_id: leaders for event_id, event_type, leaders, *_ in rows
             if event_type != 'operation' and leaders}
    by_text = members_named(texts.values(), every_username())
    return {event_id: by_text[text] for event_id, text in texts.items()}


class UnitEntry(NamedTuple):
    """One member's logged time on one period of an event, as this report
    counts it."""
    period: int
    event: int
    type: str
    started: date               # the local day the event started
    member: int
    in_field: bool              # counting.IN_FIELD: all but the AHC's time on an operation
    led: bool                   # off operations: led it, flagged OL or named in its leaders text (counting.entry_led)
    ol: bool                    # on an operation: its OL in the field (counting.entry_led)
    hours: dict                 # {local day: hours} it counts for as a member's (counting.UnitTime): its days
    span: tuple                 # as counting.UnitTime's

    @property
    def responder(self):
        """In the field on an operation."""
        return self.type == 'operation' and self.in_field


class UnitEntries(NamedTuple):
    """The time this report counts (unit_entries)."""
    entries: list               # [UnitEntry]
    first_day: date             # the first day a member attended, joined then or not; None if none has
    members: set                # the members with time counted, joined then or not


def unit_entries(now, since, joining):
    """The entries this report counts, as UnitEntries: each member's logged
    time on an event with a day it counts for by now, of events begun from
    `since` (counting.records_from), which none dated earlier claims, from
    the day the member joined (counting.Joining). Guests' time is left out.
    Every event counts, published on the calendar or not: members can see
    them all."""
    rows = list(
        Participant.objects.filter(HAS_TIME, period__event__in=reported_events(since))
        .exclude(member__status__in=Member.GUESTS)
        .annotate(in_field=ExpressionWrapper(IN_FIELD, output_field=BooleanField()))
        .order_by(*ENTRY_ORDER)
        .values_list('period__event_id', 'period__event__type', 'period__event__leaders', 'period__event__start_at',
                     'member_id', 'in_field', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at',
                     'period_id'))
    named = _named_leaders(rows)         # event -> the members its leaders text names
    start_day = {}                       # event -> the local day it started
    tz = timezone.get_current_timezone()                 # looked up once, not for every entry
    times = unit_time([(member_id, start_at, *logged) for _, _, _, start_at, member_id, _, _, *logged, _ in rows],
                      now, since, joining, tz)
    entries, members = [], set()
    for (event_id, event_type, _, start_at, member_id, in_field, ol, *_, period_id), time in zip(rows, times):
        if time.counted:
            members.add(member_id)
        if not time.hours:
            continue
        if event_id not in start_day:
            start_day[event_id] = start_at.astimezone(tz).date()
        operation = event_type == 'operation'
        leading = entry_led(event_type, ol, in_field, member_id in named.get(event_id, ()))
        entries.append(UnitEntry(
            period=period_id, event=event_id, type=event_type, started=start_day[event_id], member=member_id,
            in_field=in_field, led=leading and not operation, ol=leading and operation, hours=time.hours,
            span=time.span))
    return UnitEntries(entries, min((day for time in times for day in time.counted), default=None), members)


def _spells(member_days, months):
    """A member's stretches of days, oldest first, with no gap of more than
    `months` calendar months between days: [first day, last day] for each."""
    spells = [[member_days[0], member_days[0]]]
    for day in member_days[1:]:
        # No calendar month is shorter than 28 days, so only a longer gap needs the calendar.
        gap = (day - spells[-1][1]).days
        if gap > 28 * months and day > months_after(spells[-1][1], months):
            spells.append([day, day])
        else:
            spells[-1][1] = day
    return spells


class MemberTenure(NamedTuple):
    """A member's time on the team, from joining to their last reportable
    day, and what they attended in it, as the records hold it."""
    current: bool               # a current member (Member.CURRENT_MEMBERS); the rest are alumni
    events: int                 # of every type
    operations: int
    trainings: int
    years: int                  # whole years from joining to that last day


class Retention(NamedTuple):
    """Who was active in each year, who joined, who left and who came back."""
    active: dict                # year -> Counter((the year they joined, None for one known only to have joined
                                #   by the records' first year; whole years on the team): members active)
    flows: dict                 # months of report_settings' LEFT_AFTER -> flow -> Counter(year: members)
    records_from: int           # the year the records of joining start
    tenure: list                # [MemberTenure], one for each member counted


def _retention(entries, entered, first_attended, today, report_from, joining):
    """Retention, from the entries counted, each from the day its member
    joined (counting.Joining), of every member with time counted (`entered`)
    who has joined, whether or not they logged any since."""
    reportable_days = defaultdict(set)   # member -> their days at a reportable event
    attended = defaultdict(set)          # member -> (type, event) of each event they attended
    for entry in entries:
        if entry.type in REPORTABLE:
            reportable_days[entry.member].update(entry.hours)
        attended[entry.member].add((entry.type, entry.event))
    # The records start where the activity does, but not before the report's first year: a stray early
    # record does not move them, nor does an endorsement dated before them.
    records_from = max(first_attended.year if first_attended else today.year, report_from)
    start = date(records_from, 1, 1)
    # Those who may have joined before the records' first year: their years are kept apart (Retention.active).
    joined_members = [member for member in entered if member in joining.on]
    early = {member for member in joined_members if joining.on[member].year <= records_from and member in joining.by}
    # A member's reportable days, all since they joined. The day of joining counts, whatever the event, from
    # the records' first year; whoever joined earlier counts as there when they start.
    reportable = {}                      # member -> (the day they joined, their reportable days since)
    for member in joined_members:
        joined, member_days = joining.on[member], set(reportable_days[member])
        if joined >= start:
            member_days.add(joined)
        if member_days:
            reportable[member] = (joined, member_days)
    active_in = defaultdict(Counter)                     # as Retention.active
    left_after = report_settings().LEFT_AFTER
    flows = {months: {kind: Counter() for kind in FLOW_KINDS} for months in left_after}   # -> flow -> year -> members
    tenure = []
    current = set(Member.objects.filter(id__in=list(reportable), status__in=Member.CURRENT_MEMBERS)
                  .values_list('id', flat=True))
    for member, (joined, member_days) in reportable.items():
        member_days = sorted(member_days)
        since_joining = Counter(t for t, _ in attended[member])
        tenure.append(MemberTenure(
            current=member in current, events=sum(since_joining.values()),
            operations=since_joining['operation'], trainings=since_joining['training'],
            years=whole_months(joined, member_days[-1]) // 12))
        cohort = None if member in early else joined.year
        for months in left_after:
            spells = _spells(member_days, months)
            for number, (first, last) in enumerate(spells):
                if number:
                    flows[months]['came_back'][first.year] += 1
                elif cohort is not None and joined >= start:     # their first stretch starts the day they joined
                    flows[months]['joined'][first.year] += 1
                if today > months_after(last, months):
                    flows[months]['left' if number == len(spells) - 1 else 'left_returned'][last.year] += 1
        # Active in each year of a stretch, the year of its last day included, and once in a year that two
        # stretches share, with their whole years on the team at the year's end, or today.
        for year in {year for first, last in _spells(member_days, left_after[0])
                     for year in range(first.year, last.year + 1)}:
            active_in[year][(cohort, whole_months(joined, min(date(year, 12, 31), today)) // 12)] += 1
    return Retention(active_in, flows, records_from, tenure)


def _roles(entries):
    """Who attended each type of event in each year, and in what role:
    {(type, year): {role: members}}, for each of ROLES. Each member counts
    once: whoever led at all is counted as leading."""
    attended, led = defaultdict(set), defaultdict(set)  # (type, year) -> members
    for entry in entries:
        for day in entry.hours:
            attended[(entry.type, day.year)].add(entry.member)
            if entry.led or entry.ol:
                led[(entry.type, day.year)].add(entry.member)
    return {key: {'others': len(members - led[key]), 'led': len(led[key])} for key, members in attended.items()}


def _runs(days_out, spans_on):
    """Stretches of days in a row, by how long they ran: Counter((the year
    it started, one of RUN_LENGTHS)), from each member's days out,
    {member: {days}}, and spans_on(member, day), the (start, end) they logged
    for a day, which make a one-day stretch a long day when they run past
    report_settings' LONG_DAY."""
    long_day = timedelta(hours=report_settings().LONG_DAY)
    runs = Counter()
    for member, days in days_out.items():
        out = sorted(days)
        first = 0
        for at, day in enumerate(out):
            if at + 1 < len(out) and (out[at + 1] - day).days == 1:
                continue
            length = at - first + 1
            if length == 1:
                # Time logged twice, on two periods say, counts once. Added up as times, which are exact, as
                # fractions of an hour are not: 12 hours in three parts may come to a little over 12.
                claims = first_claims(spans_on(member, day))
                logged = sum((end - start for start, end in filter(None, claims)), timedelta())
                name = 'long_day' if logged > long_day else 'day'
            else:
                name = 'two' if length == 2 else 'more'
            runs[(out[first].year, name)] += 1
            first = at + 1
    return runs


def _stretches(entries):
    """Each member's stretches of days in a row in the field on operations,
    by how long they ran (_runs). An entry too long to be right is left out."""
    outings = defaultdict(list)          # member -> (its days, (start, end) logged) for each entry in the field
    for entry in entries:
        if entry.responder and entry.span:
            outings[entry.member].append((entry.hours.keys(), entry.span))
    return _runs({member: {day for days, _ in member_outings for day in days}
                  for member, member_outings in outings.items()},
                 lambda member, day: [span for days, span in outings[member] if day in days])


def _op_stretches(entries, ops):
    """Each member's stretches of OPs on days in a row in the field on
    operations, by how many days they ran (_runs), from the OPs they
    attended (unit_ops): a one-day stretch is long by the time they logged
    in the field on its OPs, none for an OP with one time alone."""
    spans = defaultdict(list)            # (member, OP) -> (start, end) logged on it in the field
    for entry in entries:
        if entry.responder and entry.span:
            spans[(entry.member, entry.period)].append(entry.span)
    out_on = defaultdict(lambda: defaultdict(list))     # member -> day -> the OPs they were out on
    for op in ops:
        if op.responder:
            out_on[op.member][op.day].append(op.period)
    return _runs({member: set(days) for member, days in out_on.items()},
                 lambda member, day: [span for period in out_on[member][day] for span in spans[(member, period)]])


def _responders(entries):
    """{operation: the members in the field on it}, for each that has any."""
    responders = defaultdict(set)
    for entry in entries:
        if entry.responder:
            responders[entry.event].add(entry.member)
    return responders


class ByStatus(NamedTuple):
    """Responders' days, hours, operations and OPs in the field by the status they held."""
    days: Counter               # (year, status) -> responder-days
    hours: Counter              # (year, status) -> their hours on those days
    events: Counter             # (year, status) -> operations attended, each once for each responder
    ops: Counter                # (year, status) -> responder-OPs, each day's OPs once for each responder
    since: date                 # the day status history starts; None without one
    endorsed_from: int          # from this year, statuses before `since` come from endorsements; None if none do


def _by_status(entries, responders, ops, endorsed):
    """ByStatus, from the entries counted, each operation's responders, the
    OPs members attended (unit_ops) and the day each member earned each
    endorsement (counting.endorsements)."""
    field_hours = Counter()              # (member, day) -> hours in the field on an operation, 0 for an entry too long
    started = {}                         # operation -> the local day it started
    for entry in entries:
        if entry.responder:
            for day, on_day in entry.hours.items():
                field_hours[(entry.member, day)] += on_day
            started[entry.event] = entry.started
    # A history row is written at every save of a member, and every login is one: only a member's
    # first row and those where the status changed are fetched. Rows saved at the same moment are
    # taken in the order they were saved.
    history = defaultdict(list)          # member -> [(when, status)], oldest first
    in_order = [F('history_date').asc(), F('history_id').asc()]
    out_on_ops = {(op.member, op.day) for op in ops if op.responder}          # a responder's OPs, a day once
    out_on_days = {member for member, _ in field_hours}
    changes = (Member.history.filter(id__in=out_on_days | {member for member, _ in out_on_ops})
               .annotate(before=Window(Lag('status'), partition_by=F('id'), order_by=in_order))
               .filter(Q(before__isnull=True) | ~Q(before=F('status'))))
    for member_id, when, status in changes.order_by(*in_order).values_list('id', 'history_date', 'status'):
        history[member_id].append((timezone.localtime(when).date(), status))
    # From the responders on days alone, so that responders on OPs alone change no figure of days or hours.
    status_from = min((history[member][0][0] for member in out_on_days if history[member]), default=None)
    rules = report_settings()
    banded, endorsed_from = rules.BANDED_STATUSES, date(rules.OPERATION_TIMES_FROM, 1, 1)
    earned = defaultdict(list)           # member -> [(day, its band's place in banded)], oldest first
    for (member_id, name), day in endorsed.items():
        if name in banded:
            earned[member_id].append((day, banded.index(name)))
    for days in earned.values():
        days.sort()
    read_from_endorsements = False

    def status_on(member_id, day):
        nonlocal read_from_endorsements
        if status_from is not None and day >= status_from:
            member_changes = history[member_id]
            if not member_changes:       # a member with no recorded status at all
                return OTHER_STATUS
            # The status on the day; for someone first recorded later, their first.
            status = member_changes[max(bisect_right(member_changes, (day, chr(0x10ffff))) - 1, 0)][1]
            return status if status in banded else OTHER_STATUS
        if day < endorsed_from or not earned:
            return None
        read_from_endorsements = True
        held = bisect_right(earned[member_id], (day, len(banded))) - 1
        return banded[earned[member_id][held][1]] if held >= 0 else OTHER_STATUS

    status_days = Counter()              # (year, status) -> responder-days
    status_hours = Counter()             # (year, status) -> their hours on those days
    status_events = Counter()            # (year, status) -> operations they responded to
    for (member_id, day), on_day in field_hours.items():
        status = status_on(member_id, day)
        if status:
            status_days[(day.year, status)] += 1
            status_hours[(day.year, status)] += on_day
    for event_id, responders_out in responders.items():
        day = started[event_id]
        for member_id in responders_out:
            status = status_on(member_id, day)
            if status:
                status_events[(day.year, status)] += 1
    status_ops = Counter()               # (year, status) -> responder-OPs
    for member_id, day in out_on_ops:
        status = status_on(member_id, day)
        if status:
            status_ops[(day.year, status)] += 1
    return ByStatus(status_days, status_hours, status_events, status_ops, status_from,
                    endorsed_from.year if read_from_endorsements else None)


class Replies(NamedTuple):
    """How soon members replied to callout pages: each member once for a page
    and its repages, its chain, from the first page of it they were sent."""
    by_year: dict               # the year sent -> Counter(how soon: callouts to members)
    by_hour: Counter            # (day sent, hour sent, how soon) -> callouts to members


def _replies(callout_pages, joining):
    """Replies to these callout pages, from members other than guests, to
    pages first sent from the day they joined (counting.Joining). A
    member in one of their busy periods (Unavailable, from start_on to end_on,
    both days in, as the site's own list of replies marks a page 'unavail') on
    the local day of the first page is left out of it, reply or none: they
    said they could not go, so no reply was expected of them. The periods are
    read as they stand: the site keeps no history of them."""
    first, second = report_settings().REPLY_MINUTES
    reply_speed = Cuts(zip(REPLY_SPEEDS, (first * 60, second * 60, None)))      # in seconds
    chain_of = {}                        # page -> the first page of its chain
    sent_to = defaultdict(list)          # (chain, member) -> (when sent, replied, seconds) for each page
    for page_id, ancestry, sent_at, replied, seconds, member_id in (
            Distribution.objects.filter(message__in=callout_pages).exclude(member__status__in=Member.GUESTS)
            .values_list('message_id', 'message__ancestry', 'message__created_at', 'rsvp', 'response_seconds',
                         'member_id')):
        if page_id not in chain_of:      # the pages before it are listed by id, between commas or slashes
            chain_of[page_id] = min([int(i) for i in re.findall(r'\d+', ancestry or '')] + [page_id])
        sent_to[(chain_of[page_id], member_id)].append((sent_at, replied, seconds))
    busy = defaultdict(list)             # member -> (first day, last day) of each busy period
    for member_id, start, end in Unavailable.objects.values_list('member_id', 'start_on', 'end_on'):
        if start and end:
            busy[member_id].append((start, end))
    replies = defaultdict(Counter)       # year -> how soon -> callouts to members
    reply_hours = Counter()              # (day sent, hour, how soon) -> callouts to members
    for (_, member_id), pages in sent_to.items():
        first_sent = min(sent_at for sent_at, _, _ in pages)
        # Only a reply timed after its page was sent has a usable time.
        replied_at = [sent_at + timedelta(seconds=seconds) for sent_at, _, seconds in pages
                      if seconds is not None and seconds >= 0]
        sent = timezone.localtime(first_sent)
        if not joining.member_on(member_id, sent.date()) or any(start <= sent.date() <= end
                                                                 for start, end in busy[member_id]):
            continue
        if replied_at:
            reply = reply_speed.name_for((min(replied_at) - first_sent).total_seconds())
        else:
            reply = 'untimed' if any(replied for _, replied, _ in pages) else 'none'
        replies[sent.year][reply] += 1
        reply_hours[(sent.date(), sent.hour, reply)] += 1
    return Replies(replies, reply_hours)


def _first_out(callout_pages, now, since, joining):
    """Immediate callouts, for operations begun by now, by how soon the first
    responder left home, of those who had joined by then (counting.Joining):
    {the year the operation started: Counter(how soon: callouts)}."""
    first, second = report_settings().DEPARTURE_MINUTES
    departure_speed = Cuts(zip(DEPARTURE_SPEEDS, (first / 60, second / 60, None)))     # in hours
    starts_immediate = re.compile(report_settings().IMMEDIATE_CALLOUT, re.IGNORECASE)
    immediate = {}                       # operation -> (its year, its first immediate page)
    for event_id, start_at, sent_at, text in (callout_pages.filter(period__event__start_at__lte=now)
                                              .order_by('created_at').values_list(
                                                  'period__event_id', 'period__event__start_at', 'created_at', 'text')):
        if starts_immediate.match(text) and event_id not in immediate:
            immediate[event_id] = (timezone.localtime(start_at).year, sent_at)
    # When each member in the field on one, not a guest, left home, as logged by the end of today: on any
    # entry, whether or not it has the rest of its times yet (counting.departure_entries).
    departures = defaultdict(list)       # operation -> when each responder left home
    for left in departure_entries(now, since, joining, list(immediate)):
        departures[left.operation].append(left.left_at)
    first_out = defaultdict(Counter)     # year -> how soon -> immediate callouts
    for event_id, (year, sent_at) in immediate.items():
        # The first to leave after the page: whoever was already out did not leave in answer to it.
        after = [left_at for left_at in departures[event_id] if left_at >= sent_at]
        out = departure_speed.name_for((min(after) - sent_at).total_seconds() / 3600) if after else 'none'
        first_out[year][out] += 1
    return first_out


class Operations(NamedTuple):
    """How often the unit is called out, how often the callout is called off, and how many go."""
    outcomes: Counter           # (year, one of OUTCOMES: its responder count, or why it did not run) -> operations
    responded: list             # (the day it started, its responder count) for each that ran
    without_ol: Counter         # year -> operations that ran with no OL recorded
    day_responded: list         # (day, its responder count) for each day the unit was out on operations
    days: Counter               # (year, the day's responder count, as SIZES) -> those days
    op_responded: list          # (day, its responder count) for each day with an OP of an operation, its OPs once
    ops: Counter                # (year, the day's OP responder count, as SIZES) -> those days' OPs


def _operations(entries, responders, departed, now, templates_from, ops):
    """Operations, from the entries counted, each operation's responders with
    a day, and the departures logged (counting.departure_entries),
    those that did not run told apart from `templates_from`
    (counting.reply_templates_from); and the OPs members attended
    (unit_ops)."""
    rules = report_settings()
    responder_count = Cuts(zip(SIZES, (rules.RESPONDERS_THIN, rules.RESPONDERS_FULL - 1, None)))
    out_on = defaultdict(set)            # day -> responders in the field on it, on any operation
    with_ol = set()                      # operations with an OL in the field
    started = {}                         # operation with a responder -> the local day it started
    for entry in entries:
        if entry.responder:
            started[entry.event] = entry.started
            for day in entry.hours:
                out_on[day].add(entry.member)
            if entry.ol:
                with_ol.add(entry.event)
    # An operation ran when it has a responder: a member in the field, not a guest, with a day up to today
    # or a departure logged by then. That is counting.operations_that_ran's rule, the member page's, read
    # from these entries and the departures. A departure gives no day, so no operation day or status figure.
    went = defaultdict(set, {event_id: set(members) for event_id, members in responders.items()})
    for left in departed:
        went[left.operation].add(left.member)
        started.setdefault(left.operation, timezone.localtime(left.operation_start).date())
        if entry_led('operation', left.ol, True, False):
            with_ol.add(left.operation)
    operations = Counter()               # (year, one of OUTCOMES) -> operations
    responded = []                       # (the day it started, its responder count) for operations that ran
    without_ol = Counter()               # year -> operations that ran with no OL recorded
    for event_id, members in went.items():
        day, size = started[event_id], len(members)
        operations[(day.year, responder_count.name_for(size))] += 1
        responded.append((day, size))
        if event_id not in with_ol:
            without_ol[day.year] += 1
    # One that has finished without running was called off, or was only ever a heads-up: counting's rule,
    # the member page's too. One still under way with no time logged yet waits until it finishes.
    for not_run in operations_not_run(now, set(went), templates_from).values():
        operations[(not_run.started.year, not_run.why)] += 1
    responded.sort()                     # oldest first
    day_responded = [(day, len(members)) for day, members in out_on.items()]
    operation_days = Counter((day.year, responder_count.name_for(len(members))) for day, members in out_on.items())
    out_on_op = defaultdict(set)         # day -> the responders on that day's OPs of operations
    for op in ops:
        if op.responder:
            out_on_op[op.day].add(op.member)
    op_responded = sorted((day, len(members)) for day, members in out_on_op.items())
    operation_ops = Counter((day.year, responder_count.name_for(size)) for day, size in op_responded)
    return Operations(operations, responded, without_ol, day_responded, operation_days, op_responded, operation_ops)


def _year_and_part(day):
    """Where a day counts: in its year, and in its part of the week by its own date."""
    return day.year, PARTS_OF_WEEK.name_for(day.weekday())


def _participation(entries, ops):
    """How busy the unit is and how much its members put in, from the
    entries counted and the OPs members attended (unit_ops): {who: {measure:
    {type: Counter((year, part of the week))}}}, for each of WHOSE, the unit
    (any member out) and its members (added up), and each of MEASURES."""
    # The unit's active days and events are counting's rule, the member report's too, over the entries in
    # the field: type -> unit active days, and type -> unit event -> the day it started.
    active_days, held = unit_days_and_events((entry.event, entry.type, entry.started, entry.hours)
                                             for entry in entries if entry.in_field)
    attended_days = defaultdict(set)     # type -> (member, day) attended
    attended = defaultdict(dict)         # type -> (member, event) attended -> the day it started
    logged = defaultdict(list)           # type -> (start, end) of time logged in the field
    counted = {who: {measure: {t: Counter() for t in TYPES} for measure in MEASURES} for who in WHOSE}
    for entry in entries:
        t = entry.type
        # A member's hours go to the days they count for, as on the member's own report; an entry
        # too long to be right has none.
        for day, on_day in entry.hours.items():
            counted['people']['hours'][t][_year_and_part(day)] += on_day
        attended_days[t].update((entry.member, day) for day in entry.hours)
        # An event counts once, however long it ran, in the year it started.
        attended[t][(entry.member, entry.event)] = entry.started
        if entry.in_field and entry.span:
            logged[t].append(entry.span)
    for t in TYPES:
        # The unit's hours are those anyone was out, each once, on the calendar days they fell on.
        for start, end in filter(None, first_claims(logged[t])):
            for day, on_day in hours_by_local_day(start, end).items():
                counted['unit']['hours'][t][_year_and_part(day)] += on_day
        counted['unit']['days'][t].update(map(_year_and_part, active_days[t]))
        counted['people']['days'][t].update(_year_and_part(day) for _, day in attended_days[t])
        counted['unit']['events'][t].update(map(_year_and_part, held[t].values()))
        counted['people']['events'][t].update(map(_year_and_part, attended[t].values()))
    for t, day in {(op.type, op.day) for op in ops if op.in_field}:
        counted['unit']['ops'][t][_year_and_part(day)] += 1
    for _, t, day in {(op.member, op.type, op.day) for op in ops}:
        counted['people']['ops'][t][_year_and_part(day)] += 1
    return counted


class UnitYear(NamedTuple):
    """A year's figures on the unit's report. Each {category: n} has every
    category of its kind, in the order the kind lists them."""
    year: int
    operations: dict            # {one of OUTCOMES: operations}
    operation_days: dict        # {one of SIZES: days the unit was out with that many responders}
    operation_ops: dict         # {one of SIZES: days' OPs of operations with that many responders}
    without_ol: int             # operations that ran with no OL recorded
    members: dict               # {type: {one of ROLES: members}}
    participation: dict         # {one of WHOSE: {one of MEASURES: {type: {part of the week: amount}}}}
    status_days: dict           # {each of report_settings' BANDED_STATUSES, then OTHER_STATUS: responder-days}
    status_hours: dict          # {the same: responder-hours}
    status_events: dict         # {the same: operations attended}
    status_ops: dict            # {the same: responder-OPs}
    replies: dict               # {one of REPLY_KINDS: callouts to members}
    first_out: dict             # {one of DEPARTURE_KINDS: immediate callouts}
    runs: dict                  # {one of RUN_LENGTHS: stretches in the field, by days in a row}
    op_runs: dict               # {one of RUN_LENGTHS: stretches in the field, by OPs on days in a row}
    active: dict                # {(the year they joined, whole years on the team): members}, as Retention.active
    flows: dict                 # {months of report_settings' LEFT_AFTER: {one of FLOW_KINDS: members}}
    promoted: dict              # {each of report_settings' PROMOTIONS: members promoted to it}


class UnitCounts(NamedTuple):
    """Every count the year rows are made of, each as its function gives it."""
    participation: dict         # _participation
    operations: Operations
    roles: dict                 # _roles
    by_status: ByStatus
    replies: Replies
    first_out: dict             # _first_out
    runs: Counter               # _stretches
    op_runs: Counter            # _op_stretches
    retention: Retention
    promoted: Counter           # (year, one of report_settings' PROMOTIONS) -> members promoted


def _unit_year(year, counts, today):
    """The year's UnitYear, from the counts."""
    rules = report_settings()
    statuses = rules.BANDED_STATUSES + (OTHER_STATUS,)
    return UnitYear(
        year=year,
        operations={outcome: counts.operations.outcomes[(year, outcome)] for outcome in OUTCOMES},
        operation_days={size: counts.operations.days[(year, size)] for size in SIZES},
        operation_ops={size: counts.operations.ops[(year, size)] for size in SIZES},
        without_ol=counts.operations.without_ol[year],
        members={t: counts.roles.get((t, year), dict.fromkeys(ROLES, 0)) for t in TYPES},
        participation={who: {measure: {t: {part: by_part[(year, part)] for part in PARTS_OF_WEEK.names}
                                       for t, by_part in by_type.items()}
                             for measure, by_type in measures.items()}
                       for who, measures in counts.participation.items()},
        status_days={status: counts.by_status.days[(year, status)] for status in statuses},
        status_hours={status: counts.by_status.hours[(year, status)] for status in statuses},
        status_events={status: counts.by_status.events[(year, status)] for status in statuses},
        status_ops={status: counts.by_status.ops[(year, status)] for status in statuses},
        replies={kind: counts.replies.by_year[year][kind] for kind in REPLY_KINDS},
        first_out={kind: counts.first_out[year][kind] for kind in DEPARTURE_KINDS},
        runs={length: counts.runs[(year, length)] for length in RUN_LENGTHS},
        op_runs={length: counts.op_runs[(year, length)] for length in RUN_LENGTHS},
        active=dict(counts.retention.active[year]),
        # As known today: who left in a year counts once that many months have passed since their last day,
        # so a year's leavers are all known only once that many have passed since its own (_retention).
        flows={months: {kind: counts.retention.flows[months][kind][year] for kind in FLOW_KINDS}
               for months in rules.LEFT_AFTER},
        promoted={name: counts.promoted[(year, name)] for name in rules.PROMOTIONS})


def unit_rows(now=None):
    """Count the unit's days, hours, operations and the people on them by
    year. The entries are read once (unit_entries), and each kind of figure is
    counted from them by a function of its own; _unit_year puts the counts
    into a row for each year from the unit's first year of records to this
    one. Nothing dated before that year counts (counting.records_from): no
    event begun earlier, no day and no page sent. Returns {'today': ...,
    'first_year': that year, 'years': {year: UnitYear}, ...}, and what the
    charts without years add up, each with its day: 'responded',
    'day_responded' and 'op_responded' [(day, responder count)] for
    operations that ran, for days the unit was out and for OPs of operations
    with a responder, 'first_pages' [local time of each operation's
    first page] and 'reply_hours' {(day sent, hour, how soon): callouts to
    members}; and 'status_from', the day the first status was recorded,
    'status_endorsed_from', the year from which statuses before it are read
    from endorsements (None if none are), 'records_from', the year the
    records of joining start, 'tenure' [MemberTenure], and 'templates_from',
    the day pages first told a callout from a heads-up
    (counting.reply_templates_from), None if none has."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    since = records_from(now)
    first = since.year if since else today.year
    events = reported_events(since)
    rules = report_settings()
    endorsed = endorsements(today)
    joining = joined_on(now, since, endorsed)
    entries, first_attended, entered = unit_entries(now, since, joining)
    ops = unit_ops(now, since, joining)
    responders = _responders(entries)
    templates_from = reply_templates_from()
    # The callout pages sent up to now: pages for operations that ask who can go, by the name of their
    # reply template: callout pages, and heads-ups, which count as callout pages here, as members are
    # asked to reply quickly to those too. Of the pages the reports read (counting.pages): not the Test
    # button's, here or below.
    callout_pages = pages().filter(period__event__in=events, period__event__type='operation', created_at__lte=now,
                                   rsvp_template__name__in=(rules.CALLOUT_TEMPLATE, rules.HEADS_UP_TEMPLATE))
    participation = _participation(entries, ops)
    operations = _operations(entries, responders, departure_entries(now, since, joining), now, templates_from, ops)
    earned, only_by = endorsed           # (member, endorsement) -> the day; those whose day is only a "by" year
    promoted = Counter((day.year, name) for (member, name), day in earned.items()
                       if name in rules.PROMOTIONS and (member, name) not in only_by)
    counts = UnitCounts(participation, operations, _roles(entries), _by_status(entries, responders, ops, earned),
                        _replies(callout_pages, joining), _first_out(callout_pages, now, since, joining),
                        _stretches(entries), _op_stretches(entries, ops),
                        _retention(entries, entered, first_attended, today, first, joining), promoted)
    # The local time of each operation's first page, for operations that have started; a page sent in the
    # year before the records, for an operation begun as they start, is left out with the rest of that year.
    first_pages = [paged for paged in (timezone.localtime(paged_at) for paged_at in (
        pages().filter(period__event__in=events, period__event__type='operation', period__event__start_at__lte=now)
        .values('period__event_id').annotate(paged_at=Min('created_at')).values_list('paged_at', flat=True)))
        if paged.year >= first]
    return {'today': today, 'first_year': first,
            'years': {year: _unit_year(year, counts, today) for year in range(first, today.year + 1)},
            'responded': operations.responded, 'day_responded': operations.day_responded,
            'op_responded': operations.op_responded, 'first_pages': first_pages,
            'status_from': counts.by_status.since, 'status_endorsed_from': counts.by_status.endorsed_from,
            'reply_hours': {sent: callouts for sent, callouts in counts.replies.by_hour.items()
                            if sent[0].year >= first},
            'records_from': counts.retention.records_from, 'tenure': counts.retention.tenure,
            'templates_from': templates_from}
