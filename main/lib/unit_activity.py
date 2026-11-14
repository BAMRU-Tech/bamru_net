"""The unit activity report's charts and glossary, drawn from the rows
main.lib.unit_counting counts. What the terms mean is in the glossary at the
page's foot (unit_glossary, after the terms shared with a member's report).

- The page starts in the unit's first year of records, after any stray
  early record (counting.records_from, which unit_rows reads); each chart
  shows all it has from that year on, from its own first year with data to
  this year, empty years included.
- A chart whose columns are months, days of the week, hours or numbers of
  responders adds up every year on record, or the one year the reader picks
  from its menu.
- Few operations had their times logged before report_settings'
  OPERATION_TIMES_FROM, so what
  a chart reads from those times (whether an operation ran, who went) is
  grey before it.
"""
import calendar
from collections import Counter, defaultdict
from typing import NamedTuple

from django.contrib.humanize.templatetags.humanize import apnumber, ordinal
from django.template.defaultfilters import pluralize
from django.utils.text import get_text_list

from main.lib import charts
from main.lib.counting import EVENT_TYPES, LEADING, TYPES
from main.lib.report_settings import report_settings
from main.lib.unit_counting import DEPARTURE_SPEEDS, OTHER_STATUS, REPLY_SPEEDS, SIZES, Cuts, unit_rows
from main.models import Member


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
    said: str                   # after the number in hover text, with {} where its plural takes an s
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
        return [(number(count[band.name]), band.said.format(pluralize(count[band.name]))) for band in self]


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

# What else an operations column holds: those that did not run, called out and then called off, or only
# ever a heads-up (counting.heads_up_only), two greys with the lighter on top (and the years before times
# were logged, early_band). Heads-ups are told apart by their pages from the day those first said which they
# were (counting.reply_templates_from), and by their titles before it.
CALLED_OFF = Band('muted-light', 'called_off', 'Called off', 'called off', on_scale=False)
HEADS_UP_ONLY = Band('total', 'heads_up', 'Heads-up only', 'heads-up only', on_scale=False)
DID_NOT_RUN = Bands((CALLED_OFF, HEADS_UP_ONLY))

# The steps of a measure's blue, lightest first, for a chart of so many steps, as the charts draw them.
BLUES = {1: ('1',), 2: ('1-light', '1'), 3: ('1-light', '1', '1-strong'), 4: ('1-pale', '1-light', '1', '1-strong')}

# Arrivals and departures in a year: who joined, who came back, who left and has not been
# back, and who left and came back later. Arrivals are blue above zero, departures orange below.
FLOWS = Bands((Band('1', 'joined', 'Joined', 'joined'), Band('1-light', 'came_back', 'Came back', 'came back'),
               Band('2', 'left', 'Left', 'left'), Band('2-light', 'left_returned', 'Left, came back later',
                                                      'left, came back later')))
DEPARTURES = ('left', 'left_returned')
# Years since joining, newest first and lightest; the limit is the most years in the band. They are the
# people chart's: counting counts active members by the year they joined (UnitYear.active), and only
# that chart cuts them into bands.
YEARS_SINCE_JOINING = Cuts((('first', 0), ('early', 2), ('settled', 5), ('long', 10), ('longest', None)))
TENURE = Bands((Band('ramp-1-5', 'first', 'First year', 'in their first year'),
                 Band('ramp-2-5', 'early', '1 to 2 years', 'after 1 to 2 years'),
                 Band('ramp-3-5', 'settled', '3 to 5 years', 'after 3 to 5 years'),
                 Band('ramp-4-5', 'long', '6 to 10 years', 'after 6 to 10 years'),
                 Band('ramp-5-5', 'longest', 'Over 10 years', 'after over 10 years')))
# Who attended each type of event, counted once each: the other members, and those who led it, darker, at
# the foot.
MEMBERS = {t: Bands((Band('1-light', 'others', 'Other members', 'other member{}'),
                     Band('1', 'led', 'as ' + LEADING[t], 'as ' + LEADING[t]))) for t in TYPES}


# The bands whose words quote a team's rule are built from report_settings when a chart is drawn, by a
# function for each set.


def size_bands():
    """How many went on an operation that ran, lightest for the fewest, by
    RESPONDERS_THIN and RESPONDERS_FULL."""
    rules = report_settings()
    thin, full = rules.RESPONDERS_THIN, rules.RESPONDERS_FULL
    middle = '{} to {}'.format(thin + 1, full - 1)
    return Bands((Band('1-light', 'thin', '1 to {} responders'.format(thin), 'with 1 to {} responders'.format(thin)),
                  Band('1', 'middling', middle, 'with ' + middle),
                  Band('1-strong', 'full', '{} or more'.format(full), 'with {} or more'.format(full))))


def early_band():
    """What a chart reads from operation times, before OPERATION_TIMES_FROM,
    when few had them logged: grey."""
    year = report_settings().OPERATION_TIMES_FROM
    return Band('muted', 'early', 'Before {}'.format(year), 'before {}, few operations with times logged'.format(year),
                on_scale=False)


def from_times_band():
    """On a chart without years, what is read from operation times from
    OPERATION_TIMES_FROM on: in the key as what the view counts, named where
    it is drawn. Before then is early_band."""
    return Band('1', 'recent', '', 'from {}'.format(report_settings().OPERATION_TIMES_FROM))


def status_bands():
    """A responder's status on the day, each of BANDED_STATUSES lightest for
    the newest, named as Member.TYPES names it; any other status is grey."""
    banded, named = report_settings().BANDED_STATUSES, dict(Member.TYPES)
    return Bands(tuple(Band(colour, status, named[status], named[status])
                       for colour, status in zip(BLUES[len(banded)], banded))
                 + (Band('muted', OTHER_STATUS, 'Other status', 'Other status', on_scale=False),))


def run_bands():
    """A member's stretches in the field, shortest first and lightest, a
    one-day stretch split at LONG_DAY."""
    hours = report_settings().LONG_DAY
    up_to, over = ('{} {} hour{}'.format(edge, hours, pluralize(hours)) for edge in ('up to', 'over'))
    return Bands((Band('1-pale', 'day', '1 day, ' + up_to, 'of one day, ' + up_to),
                  Band('1-light', 'long_day', '1 day, ' + over, 'of one day, ' + over),
                  Band('1', 'two', '2 days', 'of 2 days'),
                  Band('1-strong', 'more', '3 or more days', 'of 3 or more days')))


def _how_soon(names, minutes):
    """Three bands of how soon, quickest first and lightest, named `names`:
    within the first of `minutes`, over it up to the second, and later."""
    first, second = minutes
    within = '{} minute{}'.format(first, pluralize(first))
    up_to = '{}, up to {} minute{}'.format(first, second, pluralize(second))
    later = 'an hour' if second == 60 else '{} minute{}'.format(second, pluralize(second))
    return (Band('1-light', names[0], 'Within ' + within, 'within ' + within),
            Band('1', names[1], 'Over ' + up_to, 'over ' + up_to),
            Band('1-strong', names[2], 'Over ' + later, 'over ' + later))


def reply_bands():
    """How soon a page was replied to, by REPLY_MINUTES; then replies with no
    time recorded, and pages with no reply."""
    return Bands(_how_soon(REPLY_SPEEDS, report_settings().REPLY_MINUTES)
                 + (Band('muted', 'untimed', 'Reply time not recorded', 'reply time not recorded', on_scale=False),
                    Band('total', 'none', 'No reply', 'no reply', on_scale=False)))


def departure_bands():
    """How soon the first responder left home on an immediate callout, by
    DEPARTURE_MINUTES; then callouts with no departure logged after the page."""
    return Bands(_how_soon(DEPARTURE_SPEEDS, report_settings().DEPARTURE_MINUTES)
                 + (Band('total', 'none', 'No departure logged after the page', 'no departure logged after the page',
                         on_scale=False),))


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


def _in_full(year, today):
    """A year as the figures name it: in full, and this year to today."""
    return str(year) if year < today.year else '{} to {}'.format(year, today.strftime('%d %b'))


def _year_view(rows, series, **more):
    """A view of a chart with a column for each of the year rows given, short on its axis."""
    return dict(more, max_labels=12, series=series,
                periods=[{'short': charts.year_label(r.year)} for r in rows])


def _yearly_chart(rows, today, measures, view, series, **chart):
    """A chart of one view with a column for each of the year rows given:
    `measures` [(label, title)], each title followed by the years the chart
    covers; `view`, what the view shows, for readers who cannot see it;
    `series`, its panels; the rest as charts.share_panels takes them."""
    period = _span(rows[0].year, today.year, today.year)
    return charts.share_panels([{'label': label, 'title': '{}, {}'.format(title, period)} for label, title in measures],
                               [_year_view(rows, series, label='By year', name=view)], **chart)


def _days_chart(years, today):
    """How busy the unit is, how much its members put in, and how much of
    both falls on weekdays."""
    rows = _since(years, today.year, lambda r: any(sum(r.participation['people'][measure][t].values())
                                                   for measure in ('days', 'events') for t in TYPES))
    if not rows:
        return None
    period = _span(rows[0].year, today.year, today.year)
    before, times_from = early_band(), report_settings().OPERATION_TIMES_FROM
    # Operations' days, events and hours are read from their times, few of them logged before
    # OPERATION_TIMES_FROM: grey before it.
    operations = Bands(WEEK + (before,))

    def cell(r, t, who):
        bands, early = (operations, r.year < times_from) if t == 'operation' else (WEEK, False)
        counted = []
        for measure, (write, units) in COUNTED.items():
            amount = Counter(r.participation[who][measure][t])
            total = sum(amount.values())
            head = '{}: {} {}'.format(_in_full(r.year, today), write(total), units[who].format(pluralize(total)))
            counted.append({'parts': bands.stack(Counter({before.name: total}) if early else amount), 'total': total,
                            'tip': [head, FEW_TIMES] if early else [head] + WEEK.lines(amount, write)})
        return counted

    keys = {t: (operations if t == 'operation' and rows[0].year < times_from else WEEK).key() for t in TYPES}
    views = [_year_view(rows, [{'label': label, 'key': keys[t], 'cells': [cell(r, t, who) for r in rows]}
                          for t, label in EVENT_TYPES],
                   label=view.switch,
                   titles=[title + ', by type and part of the week, ' + period for title in view.titles])
             for who, view in WHO.items()]
    return charts.share_panels(
        [{'label': label, 'title': title}
         for label, title in zip(('Days', 'Events', 'Hours'), views[0]['titles'])],
        views,
        note='How busy is the unit, how much time do its members give, and how much of it falls on weekdays?',
        name='days', start_measure='Hours', measure_switch_label='Count', view_switch_label='For')


def _operations_chart(years, today, templates_from):
    """How often the unit is called out, how often the callout is called off,
    and how many respond: counted in operations, and in the days the unit
    was out. Heads-ups are told apart by their pages from `templates_from`,
    and by their titles before it, or with no such day."""
    rows = _since(years, today.year, lambda r: any(r.operations.values()))
    if not rows:
        return None
    sizes, before, times_from = size_bands(), early_band(), report_settings().OPERATION_TIMES_FROM
    outcomes = Bands(sizes + DID_NOT_RUN + (before,))                   # a column's parts, the greys at the top

    def operations(r):
        named = _in_full(r.year, today)
        count, on_days = Counter(r.operations), Counter(r.operation_days)
        ran, total, on_days_total = sum(count[size] for size in SIZES), sum(count.values()), sum(on_days.values())
        if r.year < times_from:
            return [{'parts': outcomes.stack(Counter({before.name: total})), 'total': total,
                     'tip': ['{}: {} operation{}'.format(named, total, pluralize(total)), 'Few with times logged']},
                    {'parts': outcomes.stack(Counter({before.name: on_days_total})), 'total': on_days_total,
                     'tip': ['{}: {} day{}'.format(named, on_days_total, pluralize(on_days_total)), FEW_TIMES]}]
        # Those that did not run; where their pages did not yet tell a heads-up, before templates_from or with
        # no such day, its title did, and a line says so.
        not_run = DID_NOT_RUN.lines(count)
        if not templates_from or r.year < templates_from.year:
            not_run.append('Heads-ups told by their titles')
        elif r.year == templates_from.year:
            not_run.append('Before {}, heads-ups told by their titles'.format(templates_from.strftime('%d %b')))
        return [{'parts': outcomes.stack(count), 'total': total,
                 'tip': ['{}: {} operation{}'.format(named, total, pluralize(total)), (ran, 'ran')]
                        + sizes.lines(count) + not_run},
                {'parts': outcomes.stack(on_days), 'total': on_days_total,
                 'tip': ['{}: {} day{}'.format(named, on_days_total, pluralize(on_days_total))]
                        + sizes.lines(on_days)}]

    key = Bands(sizes + DID_NOT_RUN + ((before,) if rows[0].year < times_from else ())).key()
    return _yearly_chart(
        rows, today, [('Operations', 'Operations, by unique responder count'),
                      ('Days', 'Operation days, by unique responder count')],
        'Operations and operation days, by unique responder count',
        [{'label': '', 'key': key, 'cells': [operations(r) for r in rows]}],
        note='How often is the unit called out, how often is the callout called off, and how many go?',
        name='operations', measure_switch_label='Count')


def _responders_chart(responded, day_responded, today):
    """When the unit goes, how many go: the operations, and the days, with each
    number of responders, over every year or the one picked."""
    if not responded:
        return None
    sizes = range(1, max(size for day, size in responded + day_responded) + 1)
    before, since, times_from = early_band(), from_times_band(), report_settings().OPERATION_TIMES_FROM

    def draw(counts, named, said):
        views = []
        for label, counted, noun, named_in_key, title in (
                ('Operations', responded, 'operation', 'Operations', 'Operations at each responder count, '),
                ('Days', day_responded, 'day', 'Operation days', 'Operation days at each responder count, ')):
            count = Counter(size for day, size in counted if counts(day) and day.year >= times_from)
            early = Counter(size for day, size in counted if counts(day) and day.year < times_from)

            bands = Bands((since._replace(label=named_in_key), before))
            # The key names what this choice draws, a year before OPERATION_TIMES_FROM only the grey; or, where it
            # draws nothing, what it counts.
            key = (Bands(band for band, drawn in zip(bands, (count, early)) if drawn) or Bands(bands[:1])).key()

            def tip(size):
                total = count[size] + early[size]
                head = '{} responder{}: {} {}{}'.format(size, pluralize(size), total, noun, pluralize(total))
                if not early:
                    return [head, said]
                if not count:
                    return [head, FEW_TIMES, said]
                return [head] + bands.lines(Counter({since.name: count[size], before.name: early[size]})) + [said]

            views.append({
                'label': label, 'name': title.rstrip(', '), 'max_labels': 12, 'titles': [title + named],
                'periods': [{'short': str(size)} for size in sizes],
                'series': [{'label': '', 'key': key, 'cells': [
                    [{'parts': bands.stack(Counter({since.name: count[size], before.name: early[size]})),
                      'total': count[size] + early[size], 'tip': tip(size)}]
                    for size in sizes]}]})
        return charts.share_panels(
            [{'label': 'Operations', 'title': views[0]['titles'][0]}], views,
            note='When the unit goes, how many go?', name='responders', view_switch_label='Count')

    # Its menu takes in the days operations started and the days the unit was out, which may fall in a year
    # before any started.
    return _by_year(today, [day for day, _ in responded + day_responded], draw)


def _runs_chart(years, today):
    """How often members are out for a long day, or for days in a row."""
    rows = _since(years, today.year, lambda r: any(r.runs.values()))
    if not rows:
        return None

    runs, before, times_from = run_bands(), early_band(), report_settings().OPERATION_TIMES_FROM
    bands = Bands(runs + (before,))

    def cell(r):
        count = Counter(r.runs)
        total = sum(count.values())
        head = '{}: {} stretch{}'.format(_in_full(r.year, today), total, pluralize(total, 'es'))
        if r.year < times_from:
            return [{'parts': bands.stack(Counter({before.name: total})), 'total': total, 'tip': [head, FEW_TIMES]}]
        return [{'parts': bands.stack(count), 'total': total, 'tip': [head] + runs.lines(count)}]

    key = (bands if rows[0].year < times_from else runs).key()
    return _yearly_chart(
        rows, today, [('Stretches', 'Stretches in the field, by days in a row')],
        'Stretches in the field, by days in a row', [{'label': '', 'key': key, 'cells': [cell(r) for r in rows]}],
        note='How often are members out for a long day, or for days in a row?', name='runs')


def _status_chart(years, today):
    """Responders' days, operations and hours in the field, by the status they
    held."""
    rows = _since(years, today.year, lambda r: any(r.status_days.values()))
    if not rows:
        return None
    bands, times_from = status_bands(), report_settings().OPERATION_TIMES_FROM
    # Time in the field is read from operation times, few of them logged before OPERATION_TIMES_FROM: grey
    # before it, the lighter grey, as Other status is the darker.
    before = early_band()._replace(colour='muted-light')
    with_before = Bands(bands + (before,))

    def cell(r):
        named, days, hours, events = _in_full(r.year, today), r.status_days, r.status_hours, r.status_events
        on_days, attended, in_field = sum(days.values()), sum(events.values()), sum(hours.values())
        measures = [  # (count by status, total, head, a line for each status)
            (days, on_days, '{}: {} responder-day{}'.format(named, on_days, pluralize(on_days)), bands.lines(days)),
            (events, attended, '{}: {} operation{} attended in the field'.format(named, attended, pluralize(attended)),
             bands.lines(events)),
            (hours, in_field, '{}: {} responder-hours'.format(named, charts.hours_text(in_field)),
             bands.lines(hours, charts.hours_text))]
        if r.year < times_from:
            return [{'parts': with_before.stack(Counter({before.name: total})), 'total': total,
                     'tip': [head, FEW_TIMES]} for _, total, head, _ in measures]
        return [{'parts': with_before.stack(Counter(count)), 'total': total, 'tip': [head] + lines}
                for count, total, head, lines in measures]

    key = (with_before if rows[0].year < times_from else bands).key()
    return _yearly_chart(
        rows, today, [('Days', 'Responder-days, by status on the day'),
                      ('Events', 'Operations attended, by status at the start'),
                      ('Hours', 'Responder-hours, by status on the day')],
        'Time in the field, by status', [{'label': '', 'key': key, 'cells': [cell(r) for r in rows]}],
        note='How is time in the field split by status?',
        name='status', start_measure='Hours', measure_switch_label='Count')


class Slot(NamedTuple):
    """One column of a chart that cuts time: a month, a weekday or an hour."""
    value: int
    long: str                   # in hover text
    short: str                  # on the axis; empty to leave the column unlabelled


class Timescale(NamedTuple):
    """A way of cutting time into the columns of a chart: months, weekdays or hours."""
    slot_of: object             # the value of the slot a local time falls in
    label: str                  # the option on the switch
    by: str                     # in the title
    slots: list


HOURS = [Slot(hour, '{:02d}:00 to {:02d}:59'.format(hour, hour), '{:02d}'.format(hour) if hour % 3 == 0 else '')
         for hour in range(24)]

# When operations are first paged, on each timescale: the first is shown by default.
CALLS = (
    Timescale(lambda paged: paged.month, 'Month', 'month',
        [Slot(month, calendar.month_name[month], calendar.month_abbr[month]) for month in range(1, 13)]),
    Timescale(lambda paged: paged.weekday(), 'Day of week', 'day of week',
        [Slot(day, calendar.day_name[day], calendar.day_abbr[day]) for day in range(7)]),
    Timescale(lambda paged: paged.hour, 'Hour', 'hour', HOURS),
)


def _calls_chart(first_pages, today):
    """When operations are first paged: operations by the month, the weekday
    and the hour of their first page, over every year or the one picked."""
    if not first_pages:
        return None

    def draw(counts, named, said):
        paged_at = [paged for paged in first_pages if counts(paged.date())]
        views = []
        for scale in CALLS:
            count = Counter(scale.slot_of(paged) for paged in paged_at)
            views.append({
                'label': scale.label, 'name': 'Operations by {} of first page'.format(scale.by),
                'max_labels': 7,                           # every other month, every weekday
                'titles': ['Operations by {} of first page, {}'.format(scale.by, named)],
                'periods': [{'short': slot.short} for slot in scale.slots],
                'series': [{'label': '', 'key': [('1', 'Operations')], 'cells': [
                    [{'parts': [('1', count[slot.value])], 'total': count[slot.value],
                      'tip': ['{}: {} operation{}'.format(slot.long, count[slot.value], pluralize(count[slot.value])),
                              said]}]
                    for slot in scale.slots]}]})
        return charts.share_panels(
            [{'label': 'Operations', 'title': views[0]['titles'][0]}], views,
            note='When are operations first paged?', name='calls', view_switch_label='By')

    return _by_year(today, [paged.date() for paged in first_pages], draw)


def _replies_chart(years, today):
    """How soon the DO knows who can go: callouts to members by how long each
    took to be replied to, over the years."""
    rows = _since(years, today.year, lambda r: any(r.replies.values()))
    if not rows:
        return None
    bands = reply_bands()

    def cell(r):
        total = sum(r.replies.values())
        return [{'parts': bands.stack(r.replies), 'total': total,
                 'tip': ['{}: {} callout{} to members'.format(_in_full(r.year, today), total, pluralize(total))]
                        + bands.lines(r.replies)}]

    return _yearly_chart(
        rows, today, [('Callouts', 'Callouts to members, by time to reply')],
        'Callouts to members, by time to reply', [{'label': '', 'key': bands.key(), 'cells': [cell(r) for r in rows]}],
        note='How soon do members reply to callout pages, yes or no?', name='replies')


def _reply_hours_chart(reply_hours, today):
    """Whether the hour a callout page is sent changes how soon members reply,
    over every year or the one picked."""
    if not reply_hours:
        return None
    bands = reply_bands()

    def draw(counts, named, said):
        count = defaultdict(Counter)                     # hour -> how soon -> callouts to members
        for (day, hour, speed), callouts in reply_hours.items():
            if counts(day):
                count[hour][speed] += callouts

        def cell(long, replies):
            total = sum(replies.values())
            return [{'parts': bands.stack(replies), 'total': total,
                     'tip': ['{}: {} callout{} to members'.format(long, total, pluralize(total))]
                            + bands.lines(replies) + [said]}]

        title = 'Callouts to members, by hour and time to reply, ' + named
        return charts.share_panels(
            [{'label': 'Callouts', 'title': title}],
            [{'label': 'Hour sent', 'name': 'Callouts to members, by hour sent and time to reply',
              'max_labels': 12, 'titles': [title],
              'periods': [{'short': slot.short} for slot in HOURS],
              'series': [{'label': '', 'key': bands.key(),
                          'cells': [cell(slot.long, count[slot.value]) for slot in HOURS]}]}],
            note='How soon do members reply to callout pages sent at each hour?', name='reply_hours')

    return _by_year(today, [day for day, _, _ in reply_hours], draw)


def _immediate_chart(years, today):
    """When a callout is immediate, how soon someone is on the road."""
    rows = _since(years, today.year, lambda r: any(r.first_out.values()))
    if not rows:
        return None
    bands = departure_bands()

    def cell(r):
        total = sum(r.first_out.values())
        return [{'parts': bands.stack(r.first_out), 'total': total,
                 'tip': ['{}: {} callout{}'.format(_in_full(r.year, today), total, pluralize(total))]
                        + bands.lines(r.first_out)}]

    return _yearly_chart(
        rows, today, [('Callouts', 'Immediate callouts, by time to first departure')],
        'Immediate callouts, by time to first departure',
        [{'label': '', 'key': bands.key(), 'cells': [cell(r) for r in rows]}],
        note='When a callout is immediate, how soon does the first responder leave?', name='immediate')


def _people_chart(rows, today, records_from):
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
        count, year, total = r.active, r.year, sum(r.active.values())
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
        return [{'parts': parts, 'total': total, 'tip': ['{}: {} active'.format(_in_full(year, today), total)] + lines}]

    key = Bands(TENURE + ((earlier,) if rows[0].year - records_from < longest else ())).key()
    return _yearly_chart(
        rows, today, [('Members', 'Active members, by years since joining')],
        'Active members, by years since joining', [{'label': '', 'key': key, 'cells': [cell(r) for r in rows]}],
        note='Is the unit growing, and how do its members split between new and long-standing?', name='people')


def _flows_chart(rows, today):
    """Whether the unit gains or loses members, over the year rows given
    (None for none): arrivals above zero, departures below, and the
    difference where it can yet be told. Leaving can be read at each of
    report_settings' LEFT_AFTER months without a reportable day."""
    if not rows:
        return None
    period = _span(rows[0].year, today.year, today.year)

    def cell(r, months):
        flows, known = r.flows[months], r.left_known[months]
        left = sum(flows[name] for name in DEPARTURES)
        arrived = sum(flows.values()) - left
        said = ([_in_full(r.year, today)] + FLOWS.lines(flows)
                + [('{:+d}'.format(arrived - left), 'net change') if known else 'Net change not yet known'])
        return [{'parts': [(band.colour, -flows[band.name] if band.name in DEPARTURES else flows[band.name])
                           for band in FLOWS],
                 'total': arrived, 'tip': said, 'marker': arrived - left if known else None}]

    key = FLOWS.key() + [('marker', 'Net change')]
    title = 'Members joining and leaving each year, ' + period
    return charts.share_panels(
        [{'label': 'Members', 'title': title}],
        [_year_view(rows, [{'label': '', 'key': key, 'cells': [cell(r, months) for r in rows]}],
               label='{} month{}'.format(months, pluralize(months)), titles=[title],
               name='Members joining and leaving, left after {} month{} of no activity'.format(months,
                                                                                              pluralize(months)))
         for months in report_settings().LEFT_AFTER],
        note='How many members join or come back each year, and how many leave?',
        name='flows', view_switch_label='Left after no activity for')


def _members_chart(years, today):
    """How many people each kind of activity rests on, and how many lead it.
    Their days are on the days chart, counted for each member."""
    rows = _since(years, today.year, lambda r: any(sum(r.members[t].values()) for t in TYPES))
    if not rows:
        return None
    before, times_from = early_band(), report_settings().OPERATION_TIMES_FROM

    def cell(r, t, bands):
        count = Counter(r.members[t])
        total = sum(count.values())
        head = '{}: {} member{}'.format(_in_full(r.year, today), total, pluralize(total))
        # Who went on operations is read from the times logged, few of them before OPERATION_TIMES_FROM.
        if t == 'operation' and r.year < times_from:
            return [{'parts': bands.stack(Counter({before.name: total})), 'total': total, 'tip': [head, FEW_TIMES]}]
        tip = [head] + MEMBERS[t].lines(count)[::-1]                   # those who led first
        if t == 'operation' and r.without_ol:
            tip.append((r.without_ol, 'operation{} with no OL recorded'.format(pluralize(r.without_ol))))
        return [{'parts': bands.stack(count), 'total': total, 'tip': tip}]

    series = []
    for t, label in EVENT_TYPES:
        bands = Bands(MEMBERS[t] + ((before,) if t == 'operation' else ()))
        shown = bands if t == 'operation' and rows[0].year < times_from else MEMBERS[t]
        series.append({'label': label, 'cells': [cell(r, t, bands) for r in rows], 'key': shown.key()})
    return _yearly_chart(
        rows, today, [('Members', 'Unique member count at each type of event, and how many led')],
        'members and how many led', series,
        note='How many members attend each type of event, and how many lead it?', name='members')


# The glossary writes numbers up to nine in words, as humanize's apnumber does: these are their ordinals.
ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth')


def unit_glossary(status_from, templates_from):
    """The terms this report uses beyond those shared with a member's
    report, as [(term, definition)], for the glossary at its foot, in the
    order the page's themes use them. With no status recorded (status_from
    None), there is no status to define; templates_from is the day pages first
    said whether they were a heads-up, None if none has."""
    rules = report_settings()
    # An operation that did not run is called off or a heads-up only by its pages, from the day they first said
    # which they were; before it, or with no such day, by its title (counting.heads_up_only).
    did_not_run = 'The operation has finished with no member other than the AHC having a day attended on it up to today'
    if templates_from:
        told_apart = templates_from.strftime('%d %b %Y')
        called_off = ('{}, and was called out with an availability page. Before {}, when pages first said which they '
                      'were, every operation that did not run counts here, pages or not, unless its title calls it '
                      'a heads-up or it was never used (Events left out).'.format(did_not_run, told_apart))
        heads_up = ('{}, and no availability page was sent: only heads-ups, or no page at all. Before {}, it counts '
                    'here if its title calls it a heads-up.'.format(did_not_run, told_apart))
    else:
        called_off = '{}, and its title does not call it a heads-up.'.format(did_not_run)
        heads_up = '{}, and its title calls it a heads-up.'.format(did_not_run)
    joined_on = ORDINALS[rules.JOINED_AT - 1] if rules.JOINED_AT <= len(ORDINALS) else ordinal(rules.JOINED_AT)
    # Leaving read more slowly, where the joining and leaving chart is switched to it.
    slower = (' ({} where switched)'.format(get_text_list([str(months) for months in rules.LEFT_AFTER[1:]], 'or'))
              if rules.LEFT_AFTER[1:] else '')
    terms = [
        ('Responder',
         'A member in the field on an operation, not as AHC. A day\'s responders are everyone in the field that '
         'day, on any operation.'),
        ('Operation day', 'A unit active day on operations: two operations on the same day make one operation day.'),
        ('Responder-day, responder-hours, operations attended',
         'A responder\'s day in the field and their hours on it. Operations attended count each operation once for '
         'each responder on it.'),
        ('Called off', called_off),
        ('Heads-up only', heads_up),
        ('Before {}'.format(rules.OPERATION_TIMES_FROM), 'Few operations had their times logged.'),
        ('Stretch',
         'One member\'s run of days in a row in the field, on one operation or several. A day\'s hours run '
         'from leaving home to getting back where those times are logged, otherwise from signing in to '
         'signing out. More than {} day{} logged by one member for one event or operating period is left '
         'out.'.format(rules.MAX_ENTRY_DAYS, pluralize(rules.MAX_ENTRY_DAYS))),
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
         'An operation with a callout page {}. Timed from the first such page to the first en-route time logged '
         'after it.'.format(rules.IMMEDIATE_CALLOUT_SAID)),
        ('Member-days, events attended, member-hours',
         'Each member\'s days, events or hours, added up. Ten members out for the same 8 hours make 1 unit '
         'active day, 1 unit event and 8 unit active hours; and 10 member-days, 10 events attended and 80 '
         'member-hours.'),
        ('Unit active hours',
         'Each hour counts once, however many members were out. AHC time on operations is left out.'),
        ('Unique member count',
         'Each member counts once a year for each type of event; one who led at least once counts as leading.'),
        ('Joined',
         'A member\'s {} day at an operation or a training not open to guests; with fewer than {}, their first '
         'event. The site holds no joining or leaving date, so both are read from activity.'.format(
             joined_on, apnumber(rules.JOINED_AT))),
        ('Active',
         'Every year from joining to the year of a member\'s last operation, training or community event, except '
         'the years between leaving and coming back.'),
        ('Years since joining',
         'The year shown less the year a member joined. Members who joined in the records\' first year or '
         'earlier are shown apart until all of them have over {} years.'.format(YEARS_SINCE_JOINING[-2][1])),
        ('Left',
         '{} month{} {} passed without an operation, training or community event{}. '.format(
             rules.LEFT_AFTER[0], pluralize(rules.LEFT_AFTER[0]), pluralize(rules.LEFT_AFTER[0], 'has,have'), slower)
         + 'Counted in the year of the last one. A member still counts as active in that year, so the net change '
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
    # The page starts in the unit's first year of records (unit_rows), and every chart shows what it has from
    # then on.
    today, years = rows['today'], rows['years']
    # The retention charts cover the same years, so that they read against each other.
    left_after = report_settings().LEFT_AFTER
    retention = _since(years, today.year, lambda r: any(r.active.values()) or any(r.flows[left_after[0]].values()))
    # From what interests every member to what interests the unit's leadership.
    themes = [
        ('Operations', [
            _operations_chart(years, today, rows['templates_from']),
            _responders_chart(rows['responded'], rows['day_responded'], today),
            _runs_chart(years, today),
            _status_chart(years, today)]),
        ('Pages for operations', [
            _calls_chart(rows['first_pages'], today),
            _replies_chart(years, today),
            _reply_hours_chart(rows['reply_hours'], today),
            _immediate_chart(years, today)]),
        ('Participation', [
            _days_chart(years, today),
            _members_chart(years, today)]),
        ('Retention', [
            _people_chart(retention, today, rows['records_from']),
            _flows_chart(retention, today)]),
    ]
    sections = [{'title': title, 'charts': [chart for chart in drawn if chart]} for title, drawn in themes]
    sections = [section for section in sections if section['charts']]
    for section in sections:
        for chart in section['charts']:
            chart['wide'] = any(len(view['panels']) > 1 for view in chart['views'])
    return {'sections': sections, 'charts': [chart for section in sections for chart in section['charts']],
            'glossary': unit_glossary(rows['status_from'], rows['templates_from']),
            'period': '{} to {}'.format(rows['first_year'], today.strftime('%d %b %Y'))}
