"""The unit activity report's charts and glossary, drawn from the rows
main.lib.unit_counting counts. What the terms mean is in the glossary at the
page's foot (unit_glossary, after the terms shared with a member's report).

- The page starts in its first year with something to show, after any stray
  early record (unit_counting.first_year); each chart shows all it has from
  that year on, from its own first year with data to this year, empty years
  included.
- A chart whose columns are months, days of the week, hours or numbers of
  responders adds up every year on record, or the one year the reader picks
  from its menu.
- Few operations had their times logged before OPERATION_TIMES_FROM, so what
  a chart reads from those times (whether an operation ran, who went) is
  grey before it.
"""
import calendar
from collections import Counter, defaultdict
from typing import NamedTuple

from django.template.defaultfilters import pluralize

from main.lib import charts
from main.lib.counting import EVENT_TYPES, LEADING, REPLY_TEMPLATES_FROM, TYPES
from main.lib.unit_counting import (DEPARTURE_MINUTES, FULL, LEFT_AFTER, LONG_DAY, REPLY_MINUTES, SIZES, THIN, Cuts,
                                    first_year, unit_rows)


# Few operations had their times logged before this year, so whether one ran
# cannot be told from them: what charts read from them is grey before it.
OPERATION_TIMES_FROM = 2013
FEW_TIMES = 'Few operations with times logged'                  # a hover line of its own

# Colours, on every chart of the report: parts of a whole are steps of blue,
# a darker step for more (more responders, more days, a longer wait, longer
# in the unit, leading). Orange is only for what is taken away: members who
# left. Grey is what the records cannot say, and the pale part is nothing
# (called off, no reply). The darkest step sits at the bottom of a column,
# so the weightier part is read against the axis: two parts are the main
# blue under the light one, three put the strong one beneath them.


class Band(NamedTuple):
    """One part of a column: its colour, the name its count goes by, and how
    the key and the hover text put it."""
    colour: str
    name: str
    label: str                  # in the key
    said: str                   # after the number in hover text
    on_scale: bool = True       # a step of the measure, darker for more; not one for what is unknown or nothing


class Bands(tuple):
    """The parts of a chart's columns, listed lightest first, as the key
    reads them."""

    def key(self):
        return [(band.colour, band.label) for band in self]

    def stack(self, count):
        """A column's parts from the foot up: the steps of the measure with
        the darkest at the foot, then the bands that are not steps of it."""
        steps = [band for band in self if band.on_scale]
        return [(band.colour, count[band.name]) for band in steps[::-1] + [band for band in self if not band.on_scale]]

    def lines(self, count, number=lambda n: n):
        """A line of hover text for each band: its number, then what it is."""
        return [(number(count[band.name]), band.said) for band in self]


# Weekdays are Monday to Friday (date.weekday() 0 to 4). The weekend is the darker, at the foot of a column.
WEEK = Bands((Band('1-light', 'weekday', 'Weekday', 'on weekdays'), Band('1', 'weekend', 'Weekend', 'on weekends')))


class Who(NamedTuple):
    """Whose days, events and hours a view of the days chart counts."""
    switch: str                 # the option's label on the switch
    titles: tuple               # the title for days, events and hours


WHO = {'unit': Who('Unit (any member out)', ('Unit active days (any member out)',
                                             'Unit events (any member out)',
                                             'Unit active hours (any member out)')),
       'people': Who('Members (added up)', ('Member-days (each member\'s days, added up)',
                                            'Events attended (each member\'s events, added up)',
                                            'Member-hours (each member\'s hours, added up)'))}
# How a number of each is written, and what it is counted in, for the unit and for its members, with {}
# where the plural takes its s. Hours are written to one decimal, as on a member's report, and so are
# always plural.
COUNTED = {'days': ('{:,}'.format, {'unit': 'day{}', 'people': 'member-day{}'}),
           'events': ('{:,}'.format, {'unit': 'event{}', 'people': 'event{} attended'}),
           'hours': (charts.hours_text, {'unit': 'hours', 'people': 'member-hours'})}

# How many went on an operation that ran, lightest for the fewest.
SIZE_KEY = Bands((
    Band('1-light', 'thin', '1 to {} responders'.format(THIN), 'with 1 to {} responders'.format(THIN)),
    Band('1', 'middling', '{} to {}'.format(THIN + 1, FULL - 1), 'with {} to {}'.format(THIN + 1, FULL - 1)),
    Band('1-strong', 'full', '{} or more'.format(FULL), 'with {} or more'.format(FULL))))
# What else an operations column holds: those that did not run, called out and then called off, or only
# ever a heads-up (counting.heads_up_only), two greys with the lighter on top; and the years before times
# were logged. Heads-ups are told apart from REPLY_TEMPLATES_FROM, when pages first said which they were.
CALLED_OFF = Band('muted-light', 'called_off', 'Called off', 'called off', on_scale=False)
HEADS_UP_ONLY = Band('total', 'heads_up', 'Heads-up only', 'heads-up only', on_scale=False)
EARLY = Band('muted', 'early', 'Before {}'.format(OPERATION_TIMES_FROM),
             'before {}, few operations with times logged'.format(OPERATION_TIMES_FROM), on_scale=False)

# A responder's status on the day, lightest for the newest; any other status is grey.
STATUSES = Bands((Band('1-light', 'T', 'Trainee', 'Trainee'), Band('1', 'FM', 'Field Member', 'Field Member'),
                   Band('1-strong', 'TM', 'Technical Member', 'Technical Member'),
                   Band('muted', 'other', 'Other status', 'Other status', on_scale=False)))

# A member's stretches in the field, shortest first and lightest.
RUNS = Bands((
    Band('1-pale', 'day', '1 day, up to {} hours'.format(LONG_DAY), 'of one day, up to {} hours'.format(LONG_DAY)),
    Band('1-light', 'long_day', '1 day, over {} hours'.format(LONG_DAY), 'of one day, over {} hours'.format(LONG_DAY)),
    Band('1', 'two', '2 days', 'of 2 days'), Band('1-strong', 'more', '3 or more days', 'of 3 or more days')))
# How soon a page was replied to, quickest first and lightest; then replies with
# no time recorded, and pages with no reply.
REPLIES = Bands((Band('1-light', 'minutes', 'Within {} minutes'.format(REPLY_MINUTES[0]),
                       'within {} minutes'.format(REPLY_MINUTES[0])),
                  Band('1', 'hour', 'Over {}, up to {} minutes'.format(*REPLY_MINUTES),
                       'over {}, up to {} minutes'.format(*REPLY_MINUTES)),
                  Band('1-strong', 'later', 'Over an hour', 'over an hour'),
                  Band('muted', 'untimed', 'Reply time not recorded', 'reply time not recorded', on_scale=False),
                  Band('total', 'none', 'No reply', 'no reply', on_scale=False)))
# How soon the first responder left home on an immediate callout, quickest first and lightest; then
# callouts with no departure logged after the page.
DEPARTED = Bands((Band('1-light', 'half', 'Within {} minutes'.format(DEPARTURE_MINUTES[0]),
                        'within {} minutes'.format(DEPARTURE_MINUTES[0])),
                   Band('1', 'hour', 'Over {}, up to {} minutes'.format(*DEPARTURE_MINUTES),
                        'over {}, up to {} minutes'.format(*DEPARTURE_MINUTES)),
                   Band('1-strong', 'later', 'Over an hour', 'over an hour'),
                   Band('total', 'none', 'No departure logged after the page', 'no departure logged after the page',
                        on_scale=False)))
# Arrivals and departures in a year: who joined, who came back, who left and has not been
# back, and who left and came back later. Arrivals are blue above zero, departures orange below.
FLOWS = Bands((Band('1', 'joined', 'Joined', 'joined'), Band('1-light', 'came_back', 'Came back', 'came back'),
               Band('2', 'left', 'Left', 'left'), Band('2-light', 'left_returned', 'Left, came back later',
                                                      'left, came back later')))
DEPARTURES = ('left', 'left_returned')


def _since(years, this_year, has_data):
    """The rows a chart shows: from its first year with data to this year. None without data."""
    with_data = [y for y, r in years.items() if has_data(r)]
    if not with_data:
        return None
    return [years[y] for y in range(min(with_data), this_year + 1)]


def _span(first, last, this_year):
    """The years a chart covers; one that runs to this year runs to the present."""
    return '{} to {}'.format(first, 'Present' if last == this_year else last) if first != last else str(first)


def _by_year(today, days, draw):
    """A chart without years, with a menu to pick what it adds up: every
    year on record, shown first, or one year that has something to show.
    `days` are the days of what it counts; `draw(counts, named, said)` draws
    the chart for one choice, given a test of whether a day counts, how the
    title names the period and how the hover text does."""
    years = {day.year for day in days}
    first = min(years)
    options = [('All years', draw(lambda day: day.year >= first, _span(first, today.year, today.year),
                                  'since {}'.format(first)))]
    for year in sorted(years, reverse=True):
        options.append((str(year), draw(lambda day, year=year: day.year == year, str(year), 'in {}'.format(year))))
    return charts.with_menu(options, label='Year')


def _year_view(rows, series, **more):
    """A view of a chart with a column for each of the year rows given."""
    return dict(more, max_labels=12, series=series,
                periods=[{'short': r['short']} for r in rows])


def _days_chart(years, this_year):
    """How busy the unit is, how much its members put in, and how much of
    both falls on weekdays."""
    rows = _since(years, this_year,
                  lambda r: any(sum(r['people_days'][t].values()) + sum(r['people_events'][t].values()) for t in TYPES))
    if not rows:
        return None
    period = _span(rows[0]['year'], this_year, this_year)

    def cell(r, t, who):
        counted = []
        for measure, (write, units) in COUNTED.items():
            amount = r['{}_{}'.format(who, measure)][t]
            total = sum(amount.values())
            counted.append({
                'parts': WEEK.stack(amount), 'total': total,
                'tip': ['{}: {} {}'.format(r['label'], write(total), units[who].format(pluralize(total)))]
                       + WEEK.lines(amount, write)})
        return counted

    key = WEEK.key()
    views = [_year_view(rows, [{'label': label, 'key': key, 'cells': [cell(r, t, who) for r in rows]}
                          for t, label in EVENT_TYPES],
                   label=view.switch,
                   titles=[title + ', by type and part of the week, ' + period for title in view.titles])
             for who, view in WHO.items()]
    return charts.share_panels(
        [{'label': label, 'title': title}
         for label, title in zip(('Days', 'Events', 'Hours'), views[0]['titles'])],
        views,
        note='How busy is the unit, how much time do its members give, and how much of it falls on weekdays?',
        name='days', measure_switch_label='Count', view_switch_label='For')


def _operations_chart(years, this_year):
    """How often the unit is called out, how often the callout is called off,
    and how many respond: counted in operations, and in the days the unit
    was out."""
    rows = _since(years, this_year, lambda r: any(r['operations'].values()))
    if not rows:
        return None
    period = _span(rows[0]['year'], this_year, this_year)
    outcomes = Bands(SIZE_KEY + (CALLED_OFF, HEADS_UP_ONLY, EARLY))     # a column's parts, the greys at the top

    def operations(r):
        count, on_days = Counter(r['operations']), Counter(r['operation_days'])
        ran, total, on_days_total = sum(count[size] for size in SIZES), sum(count.values()), sum(on_days.values())
        if r['year'] < OPERATION_TIMES_FROM:
            return [{'parts': outcomes.stack(Counter(early=total)), 'total': total,
                     'tip': ['{}: {} operation{}'.format(r['label'], total, pluralize(total)),
                             'Few with times logged']},
                    {'parts': outcomes.stack(Counter(early=on_days_total)), 'total': on_days_total,
                     'tip': ['{}: {} day{}'.format(r['label'], on_days_total, pluralize(on_days_total)), FEW_TIMES]}]
        # Those that did not run: before heads-ups were told apart, a line that says so in place of theirs.
        if r['year'] < REPLY_TEMPLATES_FROM.year:
            not_run = Bands((CALLED_OFF,)).lines(count) + ['Heads-ups counted as called off']
        else:
            not_run = Bands((CALLED_OFF, HEADS_UP_ONLY)).lines(count)
            if r['year'] == REPLY_TEMPLATES_FROM.year:
                not_run.append('Before {}, heads-ups counted as called off'.format(
                    REPLY_TEMPLATES_FROM.strftime('%d %b')))
        return [{'parts': outcomes.stack(count), 'total': total,
                 'tip': ['{}: {} operation{}'.format(r['label'], total, pluralize(total)), (ran, 'ran')]
                        + SIZE_KEY.lines(count) + not_run},
                {'parts': outcomes.stack(on_days), 'total': on_days_total,
                 'tip': ['{}: {} day{}'.format(r['label'], on_days_total, pluralize(on_days_total))]
                        + SIZE_KEY.lines(on_days)}]

    # The key says from when heads-ups are told apart, on a chart that starts before then.
    heads_up = (HEADS_UP_ONLY if rows[0]['year'] > REPLY_TEMPLATES_FROM.year else HEADS_UP_ONLY._replace(
        label='{}, from {}'.format(HEADS_UP_ONLY.label, REPLY_TEMPLATES_FROM.strftime('%d %b %Y'))))
    key = Bands(SIZE_KEY + (CALLED_OFF, heads_up) + ((EARLY,) if rows[0]['year'] < OPERATION_TIMES_FROM else ())).key()
    return charts.share_panels(
        [{'label': 'Operations', 'title': 'Operations, by unique responder count, ' + period},
         {'label': 'Days', 'title': 'Operation days, by unique responder count, ' + period}],
        [_year_view(rows, [{'label': '', 'key': key, 'cells': [operations(r) for r in rows]}],
               label='By year', name='Operations and operation days, by unique responder count')],
        note='How often is the unit called out, how often is the callout called off, and how many go?',
        name='operations', measure_switch_label='Count')


def _responders_chart(responded, day_responded, today):
    """When the unit goes, how many go: the operations, and the days, with each
    number of responders, over every year or the one picked."""
    if not responded:
        return None
    sizes = range(1, max(size for day, size in responded + day_responded) + 1)

    def draw(counts, named, said):
        views = []
        for label, counted, noun, named_in_key, title in (
                ('Operations', responded, 'operation', 'Operations', 'Operations at each responder count, '),
                ('Days', day_responded, 'day', 'Operation days', 'Operation days at each responder count, ')):
            count = Counter(size for day, size in counted if counts(day) and day.year >= OPERATION_TIMES_FROM)
            early = Counter(size for day, size in counted if counts(day) and day.year < OPERATION_TIMES_FROM)

            bands = Bands((Band('1', 'recent', named_in_key, 'from {}'.format(OPERATION_TIMES_FROM)), EARLY))

            def tip(size):
                total = count[size] + early[size]
                head = '{} responder{}: {} {}{}'.format(size, pluralize(size), total, noun, pluralize(total))
                if not early:
                    return [head, said]
                if not count:
                    return [head, FEW_TIMES, said]
                return [head] + bands.lines(Counter(recent=count[size], early=early[size])) + [said]

            views.append({
                'label': label, 'name': title.rstrip(', '), 'max_labels': 12, 'titles': [title + named],
                'periods': [{'short': str(size)} for size in sizes],
                'series': [{'label': '', 'key': (bands if early else Bands(bands[:1])).key(), 'cells': [
                    [{'parts': bands.stack(Counter(recent=count[size], early=early[size])),
                      'total': count[size] + early[size], 'tip': tip(size)}]
                    for size in sizes]}]})
        return charts.share_panels(
            [{'label': 'Operations', 'title': views[0]['titles'][0]}], views,
            note='When the unit goes, how many go?', name='responders', view_switch_label='Count')

    return _by_year(today, [day for day, _ in responded], draw)


def _runs_chart(years, this_year):
    """How often members are out for a long day, or for days in a row."""
    rows = _since(years, this_year, lambda r: any(r['runs'].values()))
    if not rows:
        return None

    bands = Bands(RUNS + (EARLY,))

    def cell(r):
        count = Counter(r['runs'])
        total = sum(count.values())
        head = '{}: {} stretch{}'.format(r['label'], total, pluralize(total, 'es'))
        if r['year'] < OPERATION_TIMES_FROM:
            return [{'parts': bands.stack(Counter(early=total)), 'total': total, 'tip': [head, FEW_TIMES]}]
        return [{'parts': bands.stack(count), 'total': total, 'tip': [head] + RUNS.lines(count)}]

    key = (bands if rows[0]['year'] < OPERATION_TIMES_FROM else RUNS).key()
    return charts.share_panels(
        [{'label': 'Stretches', 'title': 'Stretches in the field, by days in a row, '
                                         + _span(rows[0]['year'], this_year, this_year)}],
        [_year_view(rows, [{'label': '', 'cells': [cell(r) for r in rows], 'key': key}], label='By year',
               name='Stretches in the field, by days in a row')],
        note='How often are members out for a long day, or for days in a row?',
        name='runs')


def _status_chart(years, this_year):
    """Responders' days, operations and hours in the field, by the status they
    held."""
    rows = _since(years, this_year, lambda r: any(r['status_days'].values()))
    if not rows:
        return None

    def cell(r):
        days, hours, events = r['status_days'], r['status_hours'], r['status_events']
        on_days, attended = sum(days.values()), sum(events.values())
        return [{'parts': STATUSES.stack(days), 'total': on_days,
                 'tip': ['{}: {} responder-day{}'.format(r['label'], on_days, pluralize(on_days))]
                        + STATUSES.lines(days)},
                {'parts': STATUSES.stack(events), 'total': attended,
                 'tip': ['{}: {} operation{} attended in the field'.format(r['label'], attended, pluralize(attended))]
                        + STATUSES.lines(events)},
                {'parts': STATUSES.stack(hours), 'total': sum(hours.values()),
                 'tip': ['{}: {} responder-hours'.format(r['label'], charts.hours_text(sum(hours.values())))]
                        + STATUSES.lines(hours, charts.hours_text)}]

    period = _span(rows[0]['year'], this_year, this_year)
    return charts.share_panels(
        [{'label': 'Days', 'title': 'Responder-days, by status on the day, ' + period},
         {'label': 'Events', 'title': 'Operations attended, by status at the start, '
                                      + period},
         {'label': 'Hours', 'title': 'Responder-hours, by status on the day, ' + period}],
        [_year_view(rows, [{'label': '', 'cells': [cell(r) for r in rows],
                       'key': STATUSES.key()}], label='By year', name='Time in the field, by status')],
        note='How is time in the field split by status?',
        name='status', measure_switch_label='Count')


class Slot(NamedTuple):
    """One column of a chart that cuts time: a month, a weekday or an hour."""
    value: int
    long: str                   # in hover text
    short: str                  # on the axis; empty to leave the column unlabelled


class Cut(NamedTuple):
    """A way of cutting time into the columns of a chart."""
    slot_of: object             # the value of the slot a local time falls in
    label: str                  # the option on the switch
    by: str                     # in the title
    slots: list


HOURS = [Slot(hour, '{:02d}:00 to {:02d}:59'.format(hour, hour), '{:02d}'.format(hour) if hour % 3 == 0 else '')
         for hour in range(24)]

# When operations are first paged, by each way of cutting time: the first is shown by default.
CALLS = (
    Cut(lambda paged: paged.month, 'Month', 'month',
        [Slot(month, calendar.month_name[month], calendar.month_abbr[month]) for month in range(1, 13)]),
    Cut(lambda paged: paged.weekday(), 'Day of week', 'day of week',
        [Slot(day, calendar.day_name[day], calendar.day_abbr[day]) for day in range(7)]),
    Cut(lambda paged: paged.hour, 'Hour', 'hour', HOURS),
)


def _calls_chart(first_pages, today):
    """When operations are first paged: operations by the month, the weekday
    and the hour of their first page, over every year or the one picked."""
    if not first_pages:
        return None

    def draw(counts, named, said):
        paged_at = [paged for paged in first_pages if counts(paged.date())]
        views = []
        for cut in CALLS:
            count = Counter(cut.slot_of(paged) for paged in paged_at)
            views.append({
                'label': cut.label, 'name': 'Operations by {} of first page'.format(cut.by),
                'max_labels': 7,                           # every other month, every weekday
                'titles': ['Operations by {} of first page, {}'.format(cut.by, named)],
                'periods': [{'short': slot.short} for slot in cut.slots],
                'series': [{'label': '', 'key': [('1', 'Operations')], 'cells': [
                    [{'parts': [('1', count[slot.value])], 'total': count[slot.value],
                      'tip': ['{}: {} operation{}'.format(slot.long, count[slot.value], pluralize(count[slot.value])),
                              said]}]
                    for slot in cut.slots]}]})
        return charts.share_panels(
            [{'label': 'Operations', 'title': views[0]['titles'][0]}], views,
            note='When are operations first paged?', name='calls', view_switch_label='By')

    return _by_year(today, [paged.date() for paged in first_pages], draw)


def _replies_chart(years, this_year):
    """How soon the DO knows who can go: callouts to members by how long each
    took to be replied to, over the years."""
    rows = _since(years, this_year, lambda r: any(r['replies'].values()))
    if not rows:
        return None

    def cell(r):
        total = sum(r['replies'].values())
        return [{'parts': REPLIES.stack(r['replies']), 'total': total,
                 'tip': ['{}: {} callout{} to members'.format(r['label'], total, pluralize(total))]
                        + REPLIES.lines(r['replies'])}]

    return charts.share_panels(
        [{'label': 'Callouts', 'title': 'Callouts to members, by time to reply, '
                                     + _span(rows[0]['year'], this_year, this_year)}],
        [_year_view(rows, [{'label': '', 'key': REPLIES.key(),
                       'cells': [cell(r) for r in rows]}], label='By year',
               name='Callouts to members, by time to reply')],
        note='How soon do members reply to callout pages, yes or no?',
        name='replies')


def _reply_hours_chart(reply_hours, today):
    """Whether the hour a callout page is sent changes how soon members reply,
    over every year or the one picked."""
    if not reply_hours:
        return None

    def draw(counts, named, said):
        count = defaultdict(Counter)                     # hour -> how soon -> callouts to members
        for (day, hour, speed), callouts in reply_hours.items():
            if counts(day):
                count[hour][speed] += callouts

        def cell(long, replies):
            total = sum(replies.values())
            return [{'parts': REPLIES.stack(replies), 'total': total,
                     'tip': ['{}: {} callout{} to members'.format(long, total, pluralize(total))]
                            + REPLIES.lines(replies) + [said]}]

        title = 'Callouts to members, by hour and time to reply, ' + named
        return charts.share_panels(
            [{'label': 'Callouts', 'title': title}],
            [{'label': 'Hour sent', 'name': 'Callouts to members, by hour sent and time to reply',
              'max_labels': 12, 'titles': [title],
              'periods': [{'short': slot.short} for slot in HOURS],
              'series': [{'label': '', 'key': REPLIES.key(),
                          'cells': [cell(slot.long, count[slot.value]) for slot in HOURS]}]}],
            note='How soon do members reply to callout pages sent at each hour?', name='reply_hours')

    return _by_year(today, [day for day, _, _ in reply_hours], draw)


def _immediate_chart(years, this_year):
    """When a callout is immediate, how soon someone is on the road."""
    rows = _since(years, this_year, lambda r: any(r['first_out'].values()))
    if not rows:
        return None

    def cell(r):
        total = sum(r['first_out'].values())
        return [{'parts': DEPARTED.stack(r['first_out']), 'total': total,
                 'tip': ['{}: {} callout{}'.format(r['label'], total, pluralize(total))]
                        + DEPARTED.lines(r['first_out'])}]

    return charts.share_panels(
        [{'label': 'Callouts', 'title': 'Immediate callouts, by time to first departure, '
                                        + _span(rows[0]['year'], this_year, this_year)}],
        [_year_view(rows, [{'label': '', 'cells': [cell(r) for r in rows],
                       'key': DEPARTED.key()}], label='By year',
               name='Immediate callouts, by time to first departure')],
        note='When a callout is immediate, how soon does the first responder leave?',
        name='immediate')


# Years since joining, newest first and lightest; the limit is the most years in the band.
YEARS_SINCE_JOINING = Cuts((('first', 0), ('early', 2), ('settled', 5), ('long', 10), ('longest', None)))
TENURE = Bands((Band('ramp-1-5', 'first', 'First year', 'in their first year'),
                 Band('ramp-2-5', 'early', '1 to 2 years', 'after 1 to 2 years'),
                 Band('ramp-3-5', 'settled', '3 to 5 years', 'after 3 to 5 years'),
                 Band('ramp-4-5', 'long', '6 to 10 years', 'after 6 to 10 years'),
                 Band('ramp-5-5', 'longest', 'Over 10 years', 'after over 10 years')))


def _people_chart(rows, this_year, records_from):
    """Whether the unit is growing, and how its members split between new
    and long-standing: each year's active members by years since joining,
    over the year rows given (None for none).
    Whoever joined as the records start may have joined earlier, so they are
    kept apart until every one of them is in the longest band."""
    if not rows:
        return None
    longest = YEARS_SINCE_JOINING[-2][1] + 1            # the fewest years in the longest band
    earlier = Band('muted', 'apart', 'Joined {} or earlier'.format(records_from),
                   'joined {} or earlier'.format(records_from), on_scale=False)

    def cell(r):
        count, year, total = r['active'], r['year'], sum(r['active'].values())
        apart = count[records_from] if year - records_from < longest else 0
        joined = defaultdict(list)                       # band -> the joining years in it, with members
        for y in count:
            if count[y] and y <= year and (y > records_from or not apart):
                joined[YEARS_SINCE_JOINING.name_for(year - y)].append(y)
        parts, lines = [(earlier.colour, apart)], []         # the earliest joiners at the foot
        for band in reversed(TENURE):                    # the longest at the foot
            parts.append((band.colour, sum(count[y] for y in joined[band.name])))
            if joined[band.name]:
                since, until = min(joined[band.name]), max(joined[band.name])
                joining = '{} or earlier'.format(until) if since == records_from else _span(since, until, None)
                lines.insert(0, (parts[-1][1], '{} (joined {})'.format(band.said, joining)))
        if apart:
            lines.append((apart, earlier.said))
        return [{'parts': parts, 'total': total, 'tip': ['{}: {} active'.format(r['label'], total)] + lines}]

    key = Bands(TENURE + ((earlier,) if rows[0]['year'] - records_from < longest else ())).key()
    return charts.share_panels(
        [{'label': 'Members', 'title': 'Active members, by years since joining, '
                                       + _span(rows[0]['year'], this_year, this_year)}],
        [_year_view(rows, [{'label': '', 'cells': [cell(r) for r in rows], 'key': key}], label='By year',
               name='Active members, by years since joining')],
        note='Is the unit growing, and how do its members split between new and long-standing?',
        name='people')


def _flows_chart(rows, this_year):
    """Whether the unit gains or loses members, over the year rows given
    (None for none): arrivals above zero, departures below, and the
    difference where it can yet be told. Leaving can be read at 12, 24 or 36
    months without a reportable day."""
    if not rows:
        return None
    period = _span(rows[0]['year'], this_year, this_year)

    def cell(r, months):
        flows, known = r['flows'][months], r['left_known'][months]
        left = sum(flows[name] for name in DEPARTURES)
        arrived = sum(flows.values()) - left
        said = ([r['label']] + FLOWS.lines(flows)
                + [('{:+d}'.format(arrived - left), 'net change') if known else 'Net change not yet known'])
        return [{'parts': [(band.colour, -flows[band.name] if band.name in DEPARTURES else flows[band.name])
                           for band in FLOWS],
                 'total': arrived, 'tip': said, 'marker': arrived - left if known else None}]

    key = FLOWS.key() + [('marker', 'Net change')]
    title = 'Members joining and leaving each year, ' + period
    return charts.share_panels(
        [{'label': 'Members', 'title': title}],
        [_year_view(rows, [{'label': '', 'key': key, 'cells': [cell(r, months) for r in rows]}],
               label='{} months'.format(months), titles=[title],
               name='Members joining and leaving, left after {} months of no activity'.format(months))
         for months in LEFT_AFTER],
        note='How many members join or come back each year, and how many leave?',
        name='flows', view_switch_label='Left after no activity for')


def _members_chart(years, this_year):
    """How many people each kind of activity rests on, and how many lead it.
    Their days are on the days chart, counted for each member."""
    rows = _since(years, this_year, lambda r: any(sum(r['members'][t].values()) for t in TYPES))
    if not rows:
        return None
    period = _span(rows[0]['year'], this_year, this_year)

    def cell(r, t, bands):
        count = Counter(r['members'][t])
        total = sum(count.values())
        head = '{}: {} member{}'.format(r['label'], total, pluralize(total))
        # Who went on operations is read from the times logged, few of them before OPERATION_TIMES_FROM.
        if t == 'operation' and r['year'] < OPERATION_TIMES_FROM:
            return [{'parts': bands.stack(Counter(early=total)), 'total': total, 'tip': [head, FEW_TIMES]}]
        tip = [head, (count['led'], bands[1].said),
               (count['others'], 'other member' + pluralize(count['others']))]
        if t == 'operation' and r['without_ol']:
            tip.append((r['without_ol'], 'operation{} with no OL recorded'.format(pluralize(r['without_ol']))))
        return [{'parts': bands.stack(count), 'total': total, 'tip': tip}]

    series = []
    for t, label in EVENT_TYPES:
        role = 'as ' + LEADING[t]
        bands = Bands((Band('1-light', 'others', 'Other members', 'other members'), Band('1', 'led', role, role))
                      + ((EARLY,) if t == 'operation' else ()))
        shown = bands if t == 'operation' and rows[0]['year'] < OPERATION_TIMES_FROM else Bands(bands[:2])
        series.append({'label': label, 'cells': [cell(r, t, bands) for r in rows], 'key': shown.key()})
    return charts.share_panels(
        [{'label': 'Members', 'title': 'Unique member count at each type of event, and how many led, ' + period}],
        [_year_view(rows, series, label='By year', name='members and how many led')],
        note='How many members attend each type of event, and how many lead it?',
        name='members')


def unit_glossary(status_from=None):
    """The terms this report uses beyond those shared with a member's
    report, as [(term, definition)], for the glossary at its foot, in the
    order the page's themes use them."""
    told_apart = REPLY_TEMPLATES_FROM.strftime('%d %b %Y')     # the first page that said whether it was a heads-up
    terms = [
        ('Responder',
         'A member in the field on an operation, not as AHC. A day\'s responders are everyone in the field that '
         'day, on any operation.'),
        ('Operation day', 'A unit active day on operations: two operations on the same day make one operation day.'),
        ('Responder-day, responder-hours, operations attended',
         'A responder\'s day in the field and their hours on it. Operations attended count each operation once for '
         'each responder on it.'),
        ('Called off', 'The operation was called out with an availability page, and has finished with no member '
                       'other than the AHC having a day attended on it up to today. Before {}, when pages first said '
                       'which they were, heads-ups count here too.'.format(told_apart)),
        ('Heads-up only', 'The operation has finished with no availability page sent, only heads-ups or no page at '
                          'all, and no member other than the AHC has a day attended on it up to today. Told apart '
                          'from {}.'.format(told_apart)),
        ('Before {}'.format(OPERATION_TIMES_FROM), 'Few operations had their times logged.'),
        ('Stretch',
         'One member\'s run of days in a row in the field, on one operation or several. A day\'s hours run '
         'from leaving home to getting back where those times are logged, otherwise from signing in to '
         'signing out. More than 7 days logged by one member for one event or operating period is left out.'),
    ]
    if status_from:
        terms.append(('Status',
                      'The status a member held on the day; for operations attended, on the day the operation '
                      'started. Statuses are recorded from {}; a member first recorded later is counted under their '
                      'first recorded status, and one never recorded as Other '
                      'status.'.format(status_from.strftime('%d %b %Y'))))
    return terms + [
        ('Callout page, callout to a member',
         'A heads-up or availability page for an operation: heads-ups count here, as members are asked to reply '
         'quickly to those too. A callout to a member is a page and its repages to one member, counted once, and '
         'timed from the first of them they were sent to their reply.'),
        ('Immediate callout',
         'An operation with a callout page starting "Immediate", repages included. Timed from the first such '
         'page to the first en-route time logged after it.'),
        ('Member-days, events attended, member-hours',
         'Each member\'s days, events or hours, added up. Ten members out for the same 8 hours make 1 unit '
         'active day, 1 unit event and 8 unit active hours; and 10 member-days, 10 events attended and 80 '
         'member-hours.'),
        ('Unit active hours',
         'Each hour counts once, however many members were out. AHC time on operations is left out.'),
        ('Unique member count',
         'Each member counts once a year for each type of event; one who led at least once counts as leading.'),
        ('Joined',
         'A member\'s third day at an operation or a training not open to guests; with fewer than three, '
         'their first event. BAMRU.net holds no joining or leaving date, so both are read from activity.'),
        ('Active',
         'Every year from joining to the year of a member\'s last operation, training or community event, except '
         'the years between leaving and coming back.'),
        ('Years since joining',
         'The year shown less the year a member joined. Members who joined in the records\' first year or '
         'earlier are shown apart until all of them have over 10 years.'),
        ('Left',
         '12 months have passed without an operation, training or community event (24 or 36 where switched). '
         'Counted in the year of the last one. A member still counts as active in that year, so the net change '
         'dot and the active-members chart show their leaving a year apart.'),
        ('Came back', 'The year of a member\'s next operation, training or community event after leaving.'),
    ]


def unit_activity(now=None):
    """The charts of the unit activity report under the theme each belongs
    to, in the order shown, and the time the report covers. A chart of more
    than one panel is wide: it takes the page's width. The others sit side by
    side as tiles, as many to a row as charts.css fits. Scales are shared
    from the start, so that panels read against each other."""
    rows = unit_rows(now)
    today = rows['today']
    # The page starts in its first year with something to show, after any stray early record
    # (first_year), or this year when there is nothing; every chart shows what it has from then on.
    with_data = {year for year, r in rows['years'].items()
                 if any(r['operations'].values())
                 or any(sum(r['people_days'][t].values()) + sum(r['people_events'][t].values()) for t in TYPES)}
    first = first_year(with_data) if with_data else today.year
    # Each year named for the charts: in full for the figures, short on the time axis; this year to today.
    years = {year: dict(r, label=str(year) if year < today.year else '{} to {}'.format(year, today.strftime('%d %b')),
                        short=charts.year_label(year))
             for year, r in rows['years'].items() if year >= first}
    responded = [(day, size) for day, size in rows['responded'] if day.year >= first]
    day_responded = [(day, size) for day, size in rows['day_responded'] if day.year >= first]
    first_pages = [paged for paged in rows['first_pages'] if paged.year >= first]
    reply_hours = {sent: callouts for sent, callouts in rows['reply_hours'].items() if sent[0].year >= first}
    # The retention charts cover the same years, so that they read against each other.
    retention = _since(years, today.year,
                       lambda r: any(r['active'].values()) or any(r['flows'][LEFT_AFTER[0]].values()))
    # From what interests every member to what interests the unit's leadership.
    themes = [
        ('Operations', [
            _operations_chart(years, today.year),
            _responders_chart(responded, day_responded, today),
            _runs_chart(years, today.year),
            _status_chart(years, today.year)]),
        ('Pages for operations', [
            _calls_chart(first_pages, today),
            _replies_chart(years, today.year),
            _reply_hours_chart(reply_hours, today),
            _immediate_chart(years, today.year)]),
        ('Participation', [
            _days_chart(years, today.year),
            _members_chart(years, today.year)]),
        ('Retention', [
            _people_chart(retention, today.year, rows['records_from']),
            _flows_chart(retention, today.year)]),
    ]
    sections = [{'title': title, 'charts': [chart for chart in drawn if chart]} for title, drawn in themes]
    sections = [section for section in sections if section['charts']]
    for section in sections:
        for chart in section['charts']:
            chart['wide'] = any(len(view['panels']) > 1 for view in chart['views'])
    return {'sections': sections, 'charts': [chart for section in sections for chart in section['charts']],
            'glossary': unit_glossary(rows['status_from']),
            'period': '{} to {}'.format(first, today.strftime('%d %b %Y'))}
