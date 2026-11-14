"""A member's activity report: the chart and table of their days, events and
hours against the unit's, and the glossary of terms both activity reports
share. The counting is main.lib.counting's.
"""
import calendar

from django.template.defaultfilters import pluralize
from django.utils.text import get_text_list

from main.lib import charts
from main.lib.counting import EVENT_TYPES, LEADING, TYPES, activity_rows, pages_from
from main.lib.report_settings import report_settings
from main.models import Member



def glossary(member_report=False, records_from=None):
    """The rules of the activity reports, stated once: the terms they share,
    as [(term, definition)], for reports/glossary.html, a table at the foot
    of each. A report adds its own terms after these. `member_report` adds
    what holds only on one member's report, which counts from
    `records_from` (counting.records_from)."""
    own = " On this report a member's own {} attended count too."
    rules = report_settings()
    paged_from = pages_from()
    guests = get_text_list([label for code, label in Member.TYPES if code in Member.GUESTS], 'or')
    terms = [
        ('Logged time',
         'The time between Left and Returned on the event page, or between Signed in and Signed out where '
         'either of those is missing. Being signed up with no time logged counts nothing; time as AHC '
         'counts, even on operations where nobody else logged time. Time logged twice, on two periods or '
         'events at once, counts once, for the one that began first.'),
        ('Day attended',
         'A calendar day with at least {} hour{} logged for one event or operating period. The time logged '
         'for each counts as at least one day, and {} hour{} or less as one day, even across midnight. A day '
         'counts once for each type of event and once across all types.'.format(
             rules.DAY_HOURS, pluralize(rules.DAY_HOURS), rules.SINGLE_DAY_HOURS, pluralize(rules.SINGLE_DAY_HOURS))),
        ('Unit active day',
         'A day attended by at least one member other than the AHC, at an event of that type.'
         + (own.format('days') if member_report else '')),
        ('Event attended',
         'An event with at least one day attended, up to today. It counts once, in the year or month it '
         'started, however many of its days or operating periods were attended.'),
        ('Unit event',
         'An event attended by at least one member other than the AHC.'
         + (own.format('events') if member_report else '')),
        ('Hours',
         "Hours logged on events. Under the unit's policies, no hours are logged for administrative work or DO duty."),
        ('Guests',
         'Those whose status today is {}. Their time counts only on their own activity report; someone who has '
         'since become a member counts as one for all their time.'.format(guests)),
        ('Events left out',
         'Test and demonstration events are counted nowhere.'
         + (' Nor are operations begun from {} {:%b %Y}, when pages were first recorded, that were never used: no '
            'page sent, nobody listed, and not called a heads-up.'.format(paged_from.day, paged_from)
            if paged_from else '')),
        ('Mistaken times',
         'More than {} day{} logged by one member for one event or operating period counts one day and no '
         'hours. Hours logged for an event that has not started yet, or for a day after today, are left out.'
         .format(rules.MAX_ENTRY_DAYS, pluralize(rules.MAX_ENTRY_DAYS))
         + (' Hours left out, and time counted on another row, are shown in parentheses.' if member_report else '')
         + (" Nothing dated before {}, the first year of the unit's records, counts on this report: a date that "
            'early is taken as mistyped.'.format(records_from.year) if member_report and records_from else '')),
    ]
    if member_report:
        terms += [
            ('AHC days', 'Days on operations as AHC, apart from days also in the field.'),
            ('All',
             'Every type of event together. In days, a day with more than one type counts once, under the '
             'first of Operations, Trainings, Meetings and Community.'),
        ]
    return terms


# The member chart's colours. The panel of every type together shades by
# type, strongest for operations and grey for community events; each type's
# own panel shows the role it was attended in, in three blues, darkest at
# the foot: leading, the attendance not picked out under a role, then AHC.
TYPE_COLOURS = {'operation': '1-strong', 'training': '1', 'meeting': '1-light', 'community': 'muted'}
ROLE_COLOURS = {'led': '1-strong', 'other': '1', 'ahc': '1-light'}


def _lines(role, amount, hours=False):
    """A line of a column's figures for what was done in a role, if any."""
    return [(charts.hours_text(amount) if hours else amount, 'as ' + role)] if amount else []


def _counted(label, attended, parts, whole, noun, more=()):
    """One column of days or of events, against the unit's. Parts are
    (colour, amount); `more` is further lines for its figures."""
    return {'parts': parts, 'total': whole,
            'tip': [label, ('{} of {}'.format(attended, whole), noun + pluralize(whole)), *more]}


def _logged(label, parts, more=()):
    """One column of hours."""
    hours = sum(amount for _, amount in parts)
    return {'parts': parts, 'total': hours,
            'tip': [label, (charts.hours_text(hours), 'hours'), *more]}


def _by_role(led, other, ahc=None):
    """A column's parts by role, from the foot: what was led, the rest, and
    for an operation what was done as AHC."""
    parts = [(ROLE_COLOURS['led'], led), (ROLE_COLOURS['other'], other)]
    return parts if ahc is None else parts + [(ROLE_COLOURS['ahc'], ahc)]


def _type_cells(label, r, event_type):
    """A type's own panel, as days, events and hours: the same colours
    whatever the type, with what was led (as OL, or as TL or LL) picked out
    at the foot of the column, where it can be compared from one period to
    the next."""
    days, events = r.days[event_type], r.events[event_type]
    active_days, unit_events = r.active_days[event_type], r.unit_events[event_type]
    other_hours = r.other_hours[event_type]
    if event_type == 'operation':
        ol, ahc = r.ol_days, r.ahc_days
        return [_counted(label, days, _by_role(ol, days - ol - ahc, ahc), active_days, 'day',
                         _lines(LEADING['operation'], ol) + _lines('AHC', ahc)),
                _counted(label, events, _by_role(r.ol_events, events - r.ol_events - r.ahc_events, r.ahc_events),
                         unit_events, 'event', _lines(LEADING['operation'], r.ol_events) + _lines('AHC', r.ahc_events)),
                _logged(label, _by_role(r.ol_hours, other_hours, r.ahc_hours),
                        _lines(LEADING['operation'], r.ol_hours, hours=True) + _lines('AHC', r.ahc_hours, hours=True))]
    led, led_events, led_hours = r.led_days[event_type], r.led_events[event_type], r.led_hours[event_type]
    role = LEADING[event_type]
    return [_counted(label, days, _by_role(led, days - led), active_days, 'day', _lines(role, led)),
            _counted(label, events, _by_role(led_events, events - led_events), unit_events, 'event',
                     _lines(role, led_events)),
            _logged(label, _by_role(led_hours, other_hours), _lines(role, led_hours, hours=True))]


def _all_cells(label, r):
    """Every type in one column, shaded by type."""
    def by_type(amounts):
        return [(TYPE_COLOURS[t], amounts[t]) for t in TYPES]
    return [_counted(label, r.all_days, by_type(r.first_days), r.all_active_days, 'day'),
            _counted(label, sum(r.events.values()), by_type(r.events), sum(r.unit_events.values()), 'event'),
            _logged(label, by_type(r.hours))]


def _keys(total):
    """The key under each type's panel: the colours its columns draw, in any
    period, which are those the whole of the member's record draws, in the
    order they stack from the foot, each named. Attendance is "Other
    attendance" beside a role picked out, and "Attended" alone, as it is too
    for a panel that draws nothing."""
    order = (ROLE_COLOURS['led'], ROLE_COLOURS['other'], ROLE_COLOURS['ahc'])
    keys = {}
    for t in TYPES:
        drawn = {colour for column in _type_cells('', total, t) for colour, amount in column['parts'] if amount}
        names = {ROLE_COLOURS['led']: 'as ' + LEADING[t], ROLE_COLOURS['ahc']: 'as AHC',
                 ROLE_COLOURS['other']: 'Other attendance' if drawn - {ROLE_COLOURS['other']} else 'Attended'}
        keys[t] = ([(colour, names[colour]) for colour in order if colour in drawn]
                   or [(ROLE_COLOURS['other'], 'Attended')])
    return keys


def _periods(rows):
    """The member's rows named for the reader: (years, months, the span of
    years, as "2023 to 2024"), each of years and months [(label, short,
    row)], the label for the figures and the table, the short one for the
    chart's time axis. The axis names each month of up to nine, each
    quarter of up to two years, and otherwise each January, by its year."""
    years = [(str(r.period), charts.year_label(r.period), r) for r in rows['years']]
    every = 1 if len(rows['months']) <= 9 else 3 if len(rows['months']) <= 24 else 0

    def short(year, month):
        if month == 1:
            return charts.year_label(year)
        return calendar.month_abbr[month] if every and (month - 1) % every == 0 else ''
    months = [('{} {}'.format(calendar.month_abbr[m], y), short(y, m), r)
              for r in rows['months'] for y, m in [r.period]]
    first, last = rows['years'][0].period, rows['years'][-1].period
    return years, months, str(first) if first == last else '{} to {}'.format(first, last)


def _view(label, periods, keys):
    """One view of the chart, of periods [(label, short, row)]: every type
    together first, shaded by type, then each type."""
    series = [{
        'label': 'All',
        'key': [(TYPE_COLOURS[t], type_label) for t, type_label in EVENT_TYPES],
        'cells': [_all_cells(period, r) for period, _, r in periods],
    }]
    series += [{'label': type_label, 'key': keys[t], 'cells': [_type_cells(period, r, t) for period, _, r in periods]}
               for t, type_label in EVENT_TYPES]
    return {'label': label, 'series': series, 'periods': [{'short': short} for _, short, _ in periods]}


def _pair(days, hours):
    """A table cell, "days / hours": the hours to one decimal, as the event
    lists show them, so that the rows add up to the total."""
    return '{} / {} hours'.format(days, charts.hours_text(hours))


def _table(years, total):
    """The table: one column per type as "days / hours", with plain counts
    beside operations for whichever duties the member has done, and a row
    for each year, of [(label, short, row)], and the total."""
    columns = []
    for t, label in EVENT_TYPES:
        columns.append((label, lambda r, t=t: _pair(r.days[t], r.hours[t])))
        if t == 'operation':
            columns += [(duty_label, lambda r, field=field: getattr(r, field) or '')
                        for field, duty_label in (('ol_days', 'OL days'), ('ahc_days', 'AHC days'),
                                                  ('do_days', 'DO wks'))
                        if getattr(total, field)]
    columns.append(('Total', lambda r: _pair(r.all_days, r.all_hours)))

    def table_row(label, r):
        # Each cell with its column's heading, for a screen too narrow for columns.
        return {'label': label, 'cells': [(heading, value(r)) for heading, value in columns]}

    return {
        'title': 'Days attended / hours logged',
        'columns': [heading for heading, _ in columns],
        'rows': [table_row(label, r) for label, _, r in years],
        'total': table_row('Total', total),
    }


def member_activity(member, now, entries, since, hours=None):
    """The chart and table of a member's activity, for their activity report,
    from their entries (member_entries), counted from `since` (records_from)
    on, with the hours each counts for (counting.counted_hours) if worked out
    already. Returns None when there is nothing to show."""
    rows = activity_rows(member, now, entries, since, hours)
    if rows is None:
        return None
    keys = _keys(rows['total'])
    years, months, span = _periods(rows)
    chart = charts.share_panels(
        [{'label': 'Days', 'total_label': 'Unit active days',
          'title': 'Days attended / unit active days, by type, ' + span},
         {'label': 'Events', 'total_label': 'Unit events',
          'title': 'Events attended / unit events, by type, ' + span},
         {'label': 'Hours', 'title': 'Hours logged, by type, ' + span}],
        [_view('Years', years, keys), _view('Months', months, keys)],
        note='How often does this member take part, and how does that compare with the unit?',
        name='activity', measure_switch_label='Count')
    return {'chart': chart, 'table': _table(years, rows['total'])}
