"""What the unit activity report counts, read from the database: the entries
it reads (unit_entries), the counts made of them, and unit_rows, which puts them
in rows by year for main.lib.unit_activity to draw. The terms are defined in
the report's glossary; this says what the code decides beyond them.

- The rules a member's report shares come from main.lib.counting: the hours
  an entry counts for (entries_hours), unit active days and unit events
  (unit_days_and_events), heads-ups (heads_up_only) and the events reported
  (reported_events). Which operations ran is operations_that_ran's rule, read
  from this report's own entries rather than asked again.
- Days are weekdays or weekend days by their own dates, whatever day their
  event started; an event and an operation belong to the local day they
  started. Member-hours go with the days they count for, so hours either
  side of midnight can sit on the neighbouring day; unit active hours sit
  on the calendar days the time fell on.
- A responder's status on a day is the latest recorded on or before it; for
  a member whose own history starts later, their first recorded status.
  Days before the earliest record (status_from) are left out of the split.
- An operation's first page is the earliest page sent for any of its
  periods. A repage goes to those who have not replied, and a reply to it
  is marked on every page before it, so a page and its repages count once
  for each member: from the first of them they were sent to their first
  reply, yes or no, in the year and hour that first page went out.
- An immediate callout's clock runs to the first en-route time logged at or
  after its first such page: a responder already out did not leave in
  answer to it.
- Joining and leaving are read from activity, as the database holds no
  dates for them: the rules are the glossary's (JOINED_AT, GUEST_FRIENDLY,
  REPORTABLE, LAPSE). Whoever joined in the records' first year may have
  joined earlier, so they are kept apart.
"""
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import NamedTuple

from django.db.models import BooleanField, ExpressionWrapper, F, Min, Q, Window
from django.db.models.functions import Lag
from django.utils import timezone

from main.lib.counting import (CALLOUT, HAS_TIME, HEADS_UP, IN_FIELD, TYPES, NotRun, end_of_today, entries_hours,
                               entry_led, first_claims, hours_by_local_day, logged_span, operations_not_run,
                               reported_events, too_long, unit_days_and_events)
from main.models import Distribution, Member, Message, Participant
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
THIN = 3                                 # the fewest responders: this many or fewer
FULL = 8                                 # the most: this many or more
RESPONDER_COUNTS = Cuts((('thin', THIN), ('middling', FULL - 1), ('full', None)))
SIZES = RESPONDER_COUNTS.names
NOT_RUN = (NotRun.CALLED_OFF, NotRun.HEADS_UP_ONLY)   # why an operation nobody went on did not run
OUTCOMES = SIZES + NOT_RUN
PARTS_OF_WEEK = Cuts((('weekday', 4), ('weekend', None)))       # by date.weekday(): Monday 0 to Friday 4
RECORDED_STATUSES = ('T', 'FM', 'TM')    # those a responder is counted under; any other is 'other'
STATUSES_COUNTED = RECORDED_STATUSES + ('other',)
LONG_DAY = 12                            # hours, door to door: more makes a one-day stretch a long day
RUN_LENGTHS = ('day', 'long_day', 'two', 'more')
REPLY_MINUTES = (5, 60)                  # how soon a reply came, in minutes: within the first, within the second
REPLY_SPEEDS = Cuts((('minutes', REPLY_MINUTES[0] * 60), ('hour', REPLY_MINUTES[1] * 60), ('later', None)))  # s
REPLY_KINDS = REPLY_SPEEDS.names + ('untimed', 'none')          # then a reply with no time, and none
DEPARTURE_MINUTES = (30, 60)             # how soon the first responder left home on an immediate callout
DEPARTURE_SPEEDS = Cuts((('half', DEPARTURE_MINUTES[0] / 60), ('hour', DEPARTURE_MINUTES[1] / 60),
                         ('later', None)))                      # in hours
DEPARTURE_KINDS = DEPARTURE_SPEEDS.names + ('none',)            # then no departure logged after the page
FLOW_KINDS = ('joined', 'came_back', 'left', 'left_returned')
ROLES = ('others', 'led')                # who attended an event: those who did not lead it, and those who did
WHOSE = ('unit', 'people')               # whose days, events and hours: the unit's (any member out), its members'
MEASURES = ('days', 'events', 'hours')   # what participation is counted in

# The pages that ask who can go, by the name of their reply template: callout pages, and heads-ups,
# which count as callout pages here, as members are asked to reply quickly to those too.
ASKS_AVAILABILITY = (CALLOUT, HEADS_UP)
# The DO starts an immediate callout's page with the word. A page that repeats, answers, forwards or
# updates one puts its own word before it, perhaps numbered, perhaps more than once: "Repage 2:",
# "Re:", "Fwd:", "UPDATE:".
IMMEDIATE = re.compile(r'\W*((re-?page|re|fwd?|update)\b[\s\d]*\W*)*immediate\b', re.IGNORECASE)

# What keeps a member active, and how long without it before they have left.
REPORTABLE = ('operation', 'training', 'community')
LAPSE = timedelta(days=365)
# Leaving can also be read more slowly: the months without a reportable day before a member has left.
LEFT_AFTER = (12, 24, 36)
# A member has joined on this many days at an operation or a training not open to guests.
JOINED_AT = 3
# Trainings guests may come to: SAR Basic; those whose title says "guest", other than "no guests", "not
# for guests" or a guest lecturer, speaker, instructor or presenter; and those marked G as titles are:
# "* G", "*G", "G*", "(G)", or a G at the very end ("Mock Search G"). Words may have any spaces or
# hyphens between them, so the match starts where those before "guests" (or before "for guests") do:
# after anything but a space or a hyphen, and not after the word "no" (or "not").
GUEST_FRIENDLY = re.compile(
    r'(?i:sar[\s-]*basic'
    r'|(?<![\s-])(?:(?<!\bno)(?<!\bfor)|(?<!\bnot)[\s-]*\bfor)'
    r'[\s-]*\bguests?\b(?![\s-]+(?:lectur|speak|instruct|present))'
    r'|\*\s*g\b|\bg\*|\(g\))'
    r'|\sG\s*$')


# The page starts where its records do. Years without any are shown as empty columns, but a run of this
# many empty years cuts off what came before it: a stray early record, not the start of the records.
STRAY_BEFORE = 3


def first_year(years):
    """The year a series starts: the earliest of `years` (those with data) that
    no gap of STRAY_BEFORE empty years separates from the latest."""
    first = max(years)
    for year in sorted(years, reverse=True):
        if first - year > STRAY_BEFORE:
            break
        first = year
    return first


def _named_leaders(rows):
    """{event: the ids of the members its leaders text names}, for the events
    of the entry rows given that are not operations, by the rule the event
    page links them by. Each distinct text is read once."""
    texts = {event_id: leaders for event_id, event_type, _, leaders, *_ in rows
             if event_type != 'operation' and leaders}
    by_text = members_named(texts.values(), every_username())
    return {event_id: by_text[text] for event_id, text in texts.items()}


class UnitEntry(NamedTuple):
    """One member's logged time on one period of an event, as this report
    counts it."""
    event: int
    type: str
    started: date               # the local day the event started
    member: int
    in_field: bool              # counting.IN_FIELD: all but the AHC's time on an operation
    led: bool                   # off operations: led it, flagged OL or named in its leaders text (counting.entry_led)
    ol: bool                    # on an operation: its OL in the field (counting.entry_led)
    members_only: bool          # at an operation or a training guests may not come to: a day towards joining
    hours: dict                 # {local day: hours} it counts for by now (counting.entries_hours): its days
    span: tuple                 # the (start, end) logged, up to the end of today; None when too long to be right
    en_route_at: object         # when the member left home, where that is logged

    @property
    def responder(self):
        """In the field on an operation."""
        return self.type == 'operation' and self.in_field


def unit_entries(now):
    """The entries this report counts, as UnitEntry records: each member's
    logged time on an event with a day it counts for by now. Guests' time is
    left out. Every event counts, published on the calendar or not: members
    can see them all."""
    rows = list(
        Participant.objects.filter(HAS_TIME, period__event__in=reported_events())
        .exclude(member__status__in=Member.GUESTS)
        .annotate(in_field=ExpressionWrapper(IN_FIELD, output_field=BooleanField()))
        .order_by('period__event__start_at', 'period__event_id', 'period__position', 'id')   # member_entries'
        .values_list('period__event_id', 'period__event__type', 'period__event__title', 'period__event__leaders',
                     'period__event__start_at', 'member_id', 'id', 'in_field', 'ol',
                     'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at'))
    named = _named_leaders(rows)         # event -> the members its leaders text names
    start_day = {}                       # event -> the local day it started
    tz = timezone.get_current_timezone()                 # looked up once, not for every entry
    # Of time a member logged twice, on two periods or events at once, the entry that began first keeps
    # it (counting.entries_hours, as on a member's report), given each member's entries in member_entries'
    # order, so that both reports break a tie alike.
    by_member = defaultdict(list)        # member -> (entry, the event's start, its times), in that order
    for _, _, _, _, start_at, member_id, entry_id, _, _, *times in rows:
        by_member[member_id].append((entry_id, start_at, times))
    claimed_hours = {}                   # entry -> {local day: hours} it counts for by now
    for logged in by_member.values():
        claimed_hours.update(zip([entry_id for entry_id, _, _ in logged],
                           entries_hours([(start_at, *times) for _, start_at, times in logged], now, tz)))
    # Time after today counts nothing yet: an entry's hours stop at today (entries_hours), and the time
    # it logged where counting stops (counting.end_of_today), so no total counts it.
    counting_stops = end_of_today(now, tz)
    for event_id, event_type, title, _, start_at, member_id, entry_id, in_field, ol, *times in rows:
        hours = claimed_hours[entry_id]
        if not hours:
            continue
        if event_id not in start_day:
            start_day[event_id] = start_at.astimezone(tz).date()
        operation = event_type == 'operation'
        leading = entry_led(event_type, ol, in_field, member_id in named.get(event_id, ()))
        start, end = logged_span(*times)
        yield UnitEntry(
            event=event_id, type=event_type, started=start_day[event_id], member=member_id, in_field=in_field,
            led=leading and not operation, ol=leading and operation,
            members_only=operation or (event_type == 'training' and not GUEST_FRIENDLY.search(title)),
            hours=hours, span=None if too_long(start, end, tz) else (start, min(end, counting_stops)),
            en_route_at=times[0])


def _spells(member_days, lapse):
    """A member's stretches of days, oldest first, with no gap longer than `lapse`
    between days: [first day, last day] for each."""
    spells = [[member_days[0], member_days[0]]]
    for day in member_days[1:]:
        if day - spells[-1][1] > lapse:
            spells.append([day, day])
        else:
            spells[-1][1] = day
    return spells


class Retention(NamedTuple):
    """Who was active in each year, who joined, who left and who came back."""
    active: dict                # year -> Counter(the year they joined: members active)
    flows: dict                 # months of LEFT_AFTER -> flow -> Counter(year: members)
    records_from: int           # the year the records of joining start


def _retention(entries, today, report_from):
    """Retention, from the entries counted, with the records of joining
    starting no earlier than the report's first year."""
    first_day = {}                       # member -> their first day at any event
    member_only = defaultdict(set)       # member -> their days at operations and trainings not open to guests
    reportable_days = defaultdict(set)   # member -> their days at a reportable event
    for entry in entries:
        first = min(entry.hours)
        first_day[entry.member] = min(first, first_day.get(entry.member, first))
        if entry.members_only:
            member_only[entry.member].update(entry.hours)
        if entry.type in REPORTABLE:
            reportable_days[entry.member].update(entry.hours)
    # For want of three member-only days, a member joined on their first day at any event.
    joined_on = dict(first_day)
    joined_on.update({member: sorted(days)[JOINED_AT - 1]
                      for member, days in member_only.items() if len(days) >= JOINED_AT})
    # A member's reportable days since they joined; the day of joining counts, whatever the event.
    reportable = {member: {day for day in reportable_days[member] if day >= joined} | {joined}
                  for member, joined in joined_on.items()}
    # The records start where the reportable days do, but not before the report's first year: a stray
    # early record does not move them. Whoever was there before then counts as there when they start.
    records_from = max(min((day.year for member_days in reportable.values() for day in member_days),
                           default=today.year), report_from)
    active_in = defaultdict(Counter)                     # year -> the year they joined -> members
    flows = {months: {kind: Counter() for kind in FLOW_KINDS} for months in LEFT_AFTER}   # -> flow -> year -> members
    for member_days in reportable.values():
        member_days = sorted(member_days)
        cohort = max(member_days[0].year, records_from)  # the year they joined, or the records' first
        for months in LEFT_AFTER:
            lapse = LAPSE * (months // 12)
            spells = _spells(member_days, lapse)
            for number, (first, last) in enumerate(spells):
                if number:
                    flows[months]['came_back'][first.year] += 1
                elif cohort != records_from:             # nobody is known to have joined as the records start
                    flows[months]['joined'][first.year] += 1
                if today - last > lapse:
                    flows[months]['left' if number == len(spells) - 1 else 'left_returned'][last.year] += 1
        for first, last in _spells(member_days, LAPSE):
            # Active in each year of the stretch, the year of its last day included.
            for year in range(first.year, last.year + 1):
                active_in[year][cohort] += 1
    return Retention(active_in, flows, records_from)


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


def _stretches(entries):
    """Each member's stretches of days in a row in the field on operations,
    by how long they ran: Counter((the year it started, one of RUN_LENGTHS)).
    An entry too long to be right is left out."""
    outings = defaultdict(list)          # member -> (its days, (start, end) logged) for each entry in the field
    for entry in entries:
        if entry.responder and entry.span:
            outings[entry.member].append((entry.hours.keys(), entry.span))
    runs = Counter()
    for member_outings in outings.values():
        out = sorted({day for days, _ in member_outings for day in days})
        first = 0
        for at, day in enumerate(out):
            if at + 1 < len(out) and (out[at + 1] - day).days == 1:
                continue
            length = at - first + 1
            if length == 1:
                # Time logged twice, on two periods say, counts once.
                logged = sum((end - start).total_seconds() / 3600
                             for start, end in filter(None, first_claims([span for days, span in member_outings
                                                                          if day in days])))
                name = 'long_day' if logged > LONG_DAY else 'day'
            else:
                name = 'two' if length == 2 else 'more'
            runs[(out[first].year, name)] += 1
            first = at + 1
    return runs


def _responders(entries):
    """{operation: the members in the field on it}, for each that has any."""
    responders = defaultdict(set)
    for entry in entries:
        if entry.responder:
            responders[entry.event].add(entry.member)
    return responders


class ByStatus(NamedTuple):
    """Responders' days, hours and operations in the field by the status they held."""
    days: Counter               # (year, status) -> responder-days
    hours: Counter              # (year, status) -> their hours on those days
    events: Counter             # (year, status) -> operations attended, each once for each responder
    since: date                 # the day status history starts; None without one


def _by_status(entries, responders):
    """ByStatus, from the entries counted and each operation's responders."""
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
    changes = (Member.history.filter(id__in={member for member, _ in field_hours})
               .annotate(before=Window(Lag('status'), partition_by=F('id'), order_by=in_order))
               .filter(Q(before__isnull=True) | ~Q(before=F('status'))))
    for member_id, when, status in changes.order_by(*in_order).values_list('id', 'history_date', 'status'):
        history[member_id].append((timezone.localtime(when).date(), status))
    status_from = min((member_changes[0][0] for member_changes in history.values()), default=None)

    def status_on(member_id, day):
        member_changes = history[member_id]
        if status_from is None or day < status_from:
            return None
        if not member_changes:           # a member with no recorded status at all
            return 'other'
        # The status on the day; for someone first recorded later, their first.
        status = member_changes[max(bisect_right(member_changes, (day, chr(0x10ffff))) - 1, 0)][1]
        return status if status in RECORDED_STATUSES else 'other'

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
    return ByStatus(status_days, status_hours, status_events, status_from)


class Replies(NamedTuple):
    """How soon members replied to callout pages: each member once for a page
    and its repages, its chain, from the first page of it they were sent."""
    by_year: dict               # the year sent -> Counter(how soon: callouts to members)
    by_hour: Counter            # (day sent, hour sent, how soon) -> callouts to members


def _replies(callout_pages):
    """Replies to these callout pages, from members other than guests."""
    chain_of = {}                        # page -> the first page of its chain
    sent_to = defaultdict(list)          # (chain, member) -> (when sent, replied, seconds) for each page
    for page_id, ancestry, sent_at, replied, seconds, member_id in (
            Distribution.objects.filter(message__in=callout_pages).exclude(member__status__in=Member.GUESTS)
            .values_list('message_id', 'message__ancestry', 'message__created_at', 'rsvp', 'response_seconds',
                         'member_id')):
        if page_id not in chain_of:      # the pages before it are listed by id, between commas or slashes
            chain_of[page_id] = min([int(i) for i in re.findall(r'\d+', ancestry or '')] + [page_id])
        sent_to[(chain_of[page_id], member_id)].append((sent_at, replied, seconds))
    replies = defaultdict(Counter)       # year -> how soon -> callouts to members
    reply_hours = Counter()              # (day sent, hour, how soon) -> callouts to members
    for pages in sent_to.values():
        first_sent = min(sent_at for sent_at, _, _ in pages)
        # Only a reply timed after its page was sent has a usable time.
        replied_at = [sent_at + timedelta(seconds=seconds) for sent_at, _, seconds in pages
                      if seconds is not None and seconds >= 0]
        if replied_at:
            reply = REPLY_SPEEDS.name_for((min(replied_at) - first_sent).total_seconds())
        else:
            reply = 'untimed' if any(replied for _, replied, _ in pages) else 'none'
        sent = timezone.localtime(first_sent)
        replies[sent.year][reply] += 1
        reply_hours[(sent.date(), sent.hour, reply)] += 1
    return Replies(replies, reply_hours)


def _first_out(entries, callout_pages):
    """Immediate callouts by how soon the first responder left home:
    {the year the operation started: Counter(how soon: callouts)}."""
    departures = defaultdict(list)       # operation -> when each responder left home
    for entry in entries:
        if entry.responder and entry.en_route_at:
            departures[entry.event].append(entry.en_route_at)
    immediate = {}                       # operation -> (its year, its first immediate page)
    for event_id, start_at, sent_at, text in (callout_pages.order_by('created_at').values_list(
            'period__event_id', 'period__event__start_at', 'created_at', 'text')):
        if IMMEDIATE.match(text) and event_id not in immediate:
            immediate[event_id] = (timezone.localtime(start_at).year, sent_at)
    first_out = defaultdict(Counter)     # year -> how soon -> immediate callouts
    for event_id, (year, sent_at) in immediate.items():
        # The first to leave after the page: whoever was already out did not leave in answer to it.
        after = [left_at for left_at in departures[event_id] if left_at >= sent_at]
        out = DEPARTURE_SPEEDS.name_for((min(after) - sent_at).total_seconds() / 3600) if after else 'none'
        first_out[year][out] += 1
    return first_out


class Operations(NamedTuple):
    """How often the unit is called out, how often the callout is called off, and how many go."""
    outcomes: Counter           # (year, one of OUTCOMES: its responder count, or why it did not run) -> operations
    responded: list             # (the day it started, its responder count) for each that ran
    without_ol: Counter         # year -> operations that ran with no OL recorded
    day_responded: list         # (day, its responder count) for each day the unit was out on operations
    days: Counter               # (year, the day's responder count, as RESPONDER_COUNTS) -> those days


def _operations(entries, responders, now):
    """Operations, from the entries counted and each operation's responders."""
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
    operations = Counter()               # (year, one of OUTCOMES) -> operations
    responded = []                       # (the day it started, its responder count) for operations that ran
    without_ol = Counter()               # year -> operations that ran with no OL recorded
    # An operation ran when it has a responder: a member in the field, not a guest, with a day up to
    # today. That is counting.operations_that_ran's rule, the member page's, read from these entries.
    for event_id, members in responders.items():
        day, size = started[event_id], len(members)
        operations[(day.year, RESPONDER_COUNTS.name_for(size))] += 1
        responded.append((day, size))
        if event_id not in with_ol:
            without_ol[day.year] += 1
    # One that has finished without running was called off, or was only ever a heads-up: counting's rule,
    # the member page's too. One still under way with no time logged yet waits until it finishes.
    for not_run in operations_not_run(now, set(responders)).values():
        operations[(not_run.started.year, not_run.why)] += 1
    responded.sort()                     # oldest first
    day_responded = [(day, len(members)) for day, members in out_on.items()]
    operation_days = Counter((day.year, RESPONDER_COUNTS.name_for(len(members))) for day, members in out_on.items())
    return Operations(operations, responded, without_ol, day_responded, operation_days)


def _year_and_part(day):
    """Where a day counts: in its year, and in its part of the week by its own date."""
    return day.year, PARTS_OF_WEEK.name_for(day.weekday())


def _participation(entries):
    """How busy the unit is and how much its members put in, from the
    entries counted: {who: {measure: {type: Counter((year, part of the
    week))}}}, for each of WHOSE, the unit (any member out) and its members
    (added up), and each of MEASURES."""
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
    return counted


class UnitYear(NamedTuple):
    """A year's figures on the unit's report. Each {category: n} has every
    category of its kind, in the order the kind lists them."""
    year: int
    operations: dict            # {one of OUTCOMES: operations}
    operation_days: dict        # {one of SIZES: days the unit was out with that many responders}
    without_ol: int             # operations that ran with no OL recorded
    members: dict               # {type: {one of ROLES: members}}
    participation: dict         # {one of WHOSE: {one of MEASURES: {type: {part of the week: amount}}}}
    status_days: dict           # {one of STATUSES_COUNTED: responder-days}
    status_hours: dict          # {one of STATUSES_COUNTED: responder-hours}
    status_events: dict         # {one of STATUSES_COUNTED: operations attended}
    replies: dict               # {one of REPLY_KINDS: callouts to members}
    first_out: dict             # {one of DEPARTURE_KINDS: immediate callouts}
    runs: dict                  # {one of RUN_LENGTHS: stretches in the field}
    active: dict                # {the year they joined, from the year the records of joining start: members}
    left_known: dict            # {months of LEFT_AFTER: whether who left in the year is known yet}
    flows: dict                 # {months of LEFT_AFTER: {one of FLOW_KINDS: members}}


class UnitCounts(NamedTuple):
    """Every count the year rows are made of, each as its function gives it."""
    participation: dict         # _participation
    operations: Operations
    roles: dict                 # _roles
    by_status: ByStatus
    replies: Replies
    first_out: dict             # _first_out
    runs: Counter               # _stretches
    retention: Retention


def _unit_year(year, counts, today):
    """The year's UnitYear, from the counts."""
    return UnitYear(
        year=year,
        operations={outcome: counts.operations.outcomes[(year, outcome)] for outcome in OUTCOMES},
        operation_days={size: counts.operations.days[(year, size)] for size in SIZES},
        without_ol=counts.operations.without_ol[year],
        members={t: counts.roles.get((t, year), dict.fromkeys(ROLES, 0)) for t in TYPES},
        participation={who: {measure: {t: {part: by_part[(year, part)] for part in PARTS_OF_WEEK.names}
                                       for t, by_part in by_type.items()}
                             for measure, by_type in measures.items()}
                       for who, measures in counts.participation.items()},
        status_days={status: counts.by_status.days[(year, status)] for status in STATUSES_COUNTED},
        status_hours={status: counts.by_status.hours[(year, status)] for status in STATUSES_COUNTED},
        status_events={status: counts.by_status.events[(year, status)] for status in STATUSES_COUNTED},
        replies={kind: counts.replies.by_year[year][kind] for kind in REPLY_KINDS},
        first_out={kind: counts.first_out[year][kind] for kind in DEPARTURE_KINDS},
        runs={length: counts.runs[(year, length)] for length in RUN_LENGTHS},
        active={cohort: counts.retention.active[year][cohort]
                for cohort in range(counts.retention.records_from, today.year + 1)},
        # Who left in a year is known once more than 12 months have passed since its last day, the day
        # after which a member last there on it has left.
        left_known={months: date(year, 12, 31) + LAPSE * (months // 12) < today for months in LEFT_AFTER},
        flows={months: {kind: counts.retention.flows[months][kind][year] for kind in FLOW_KINDS}
               for months in LEFT_AFTER})


def unit_rows(now=None):
    """Count the unit's days, hours, operations and the people on them by
    year. The entries are read once (unit_entries), and each kind of figure is
    counted from them by a function of its own; _unit_year puts the counts
    into a row for each year from the earliest record to this one. Returns
    {'today': ..., 'first_year': the year the report starts, after any stray
    early record (first_year), 'years': {year: UnitYear}, ...}, and what the
    charts without years add up, each with its day: 'responded' and
    'day_responded' [(day, responder count)] for operations that ran and for
    days the unit was out, 'first_pages' [local time of each operation's
    first page] and 'reply_hours' {(day sent, hour, how soon): callouts to
    members}; and 'status_from', the day the first status was recorded, and
    'records_from', the year the records of joining start."""
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    entries = list(unit_entries(now))
    responders = _responders(entries)
    # The callout pages sent up to now: pages for operations that ask who can go (ASKS_AVAILABILITY).
    callout_pages = Message.objects.filter(format='page', period__event__in=reported_events(),
                                           period__event__type='operation',
                                           rsvp_template__name__in=ASKS_AVAILABILITY, created_at__lte=now)
    participation = _participation(entries)
    operations = _operations(entries, responders, now)
    # A year has a row when anything is counted in it: a day attended, an event (in the year it started)
    # or an operation. The report starts in the first of them, after any stray early record, or this year
    # when there is nothing; joining is counted from then on.
    recorded = ({year for measure in ('days', 'events') for by_part in participation['people'][measure].values()
                 for year, _ in by_part}
                | {year for year, _ in operations.outcomes})
    first = first_year(recorded) if recorded else today.year
    counts = UnitCounts(participation, operations, _roles(entries), _by_status(entries, responders),
                        _replies(callout_pages), _first_out(entries, callout_pages), _stretches(entries),
                        _retention(entries, today, first))
    # The local time of each operation's first page, for operations that have started.
    first_pages = [timezone.localtime(paged_at) for paged_at in (
        Message.objects.filter(format='page', period__event__in=reported_events(), period__event__type='operation',
                               period__event__start_at__lte=now)
        .values('period__event_id').annotate(paged_at=Min('created_at')).values_list('paged_at', flat=True))]
    return {'today': today, 'first_year': first,
            'years': {year: _unit_year(year, counts, today)
                      for year in range(min(recorded, default=today.year), today.year + 1)},
            'responded': operations.responded, 'day_responded': operations.day_responded, 'first_pages': first_pages,
            'status_from': counts.by_status.since, 'reply_hours': counts.replies.by_hour,
            'records_from': counts.retention.records_from}
