"""A member's activity report: the chart and table of their days, events,
OPs and hours against the unit's, and the glossary of terms both activity reports
share. The counting is main.lib.counting's.
"""
import calendar

from django.template.defaultfilters import pluralize
from django.utils.text import get_text_list

from main.lib import charts
from main.lib.counting import EVENT_TYPES, LEADING, TYPES, activity_rows, pages_from
from main.lib.report_settings import ReportSettings, report_settings
from main.models import Member



def glossary(member_report=False, records_from=None):
    """The rules of the activity reports, stated once: the terms they share,
    as [(term, definition)], for reports/glossary.html, a table at the foot
    of each. A report adds its own terms after these. `member_report` adds
    what holds only on one member's report, which counts from
    `records_from` (counting.records_from)."""
    own = (" On a member's own report, every {0} they attended counts as a {1} too, even as AHC or as a guest, so "
           "the unit's figure is never below theirs.")
    rules = report_settings()
    # The worked examples of Day attended and Hours hold at the default day rules (counting's
    # DaysTestCase.test_the_glossary_s_examples_count_as_it_says), so they are shown only under them: a
    # team's own rules are stated with its numbers, without examples. Each is shorter than a day, so no limit
    # of days (MAX_ENTRY_DAYS, at least 1) touches it.
    defaults = ReportSettings()
    examples = (rules.DAY_HOURS, rules.SINGLE_DAY_HOURS) == (defaults.DAY_HOURS, defaults.SINGLE_DAY_HOURS)
    def example(text):
        return text if examples else ''
    paged_from = pages_from()
    # The guest statuses, named as examples: a no-contact one (Member.NO_CONTACT) is never named on the reports.
    named = [label for code, label in Member.TYPES if code in Member.GUESTS and code not in Member.NO_CONTACT]
    guests = 'a guest status' + (', such as ' + get_text_list(named, 'or') if named else '')
    terms = [
        ('Logged time',
         'The time from Left to Returned on the event page, or from Signed in to Signed out when Left or '
         'Returned is missing. Being signed up with no time logged counts nothing; time as AHC counts, even '
         'on operations where nobody else logged time. Time logged twice, on two periods or events at once, '
         'counts once, for the one that began first.'),
        ('Day attended',
         'Any time logged for an event or operating period counts as at least one day attended, however short: '
         'a one-hour meeting is a day. Up to {0} hour{1} counts as one day, even if it runs past midnight. That '
         'day is the date most of the time fell on{4}. More than {0} hour{1} counts each date with at least {2} '
         'hour{3} on it{5}. A date counts only once for each type of event: two meetings on one date are one '
         'day. It also counts only once across all types: a meeting and a training on one date are one day '
         'across all types.'.format(
             rules.SINGLE_DAY_HOURS, pluralize(rules.SINGLE_DAY_HOURS), rules.DAY_HOURS, pluralize(rules.DAY_HOURS),
             example(': 10pm to 4am is one day, on the second date'),
             example(': 6pm Saturday to 10am Sunday is two days, and 8am Saturday to 1am Sunday is one day, '
                     'Saturday'))),
        ('Unit active day',
         'A day attended by at least one member other than the AHC, at an event of that type.'
         + (own.format('day', 'unit active day') if member_report else '')),
        ('Event attended',
         'An event with at least one day attended, up to today. It counts once, in the year or month it '
         'started, however many of its days or operating periods were attended.'),
        ('Unit event',
         'An event attended by at least one member other than the AHC.'
         + (own.format('event', 'unit event') if member_report else '')),
        ('OP attended',
         'An operating period of an event, OP1, OP2 and so on on its page, with any time of the member\'s logged on '
         'it: one time alone counts, such as Left with no Returned. Each OP is one calendar day: in their order on '
         'the page, the first is the day the event starts, the next the day after, and so on, whatever its times '
         'say. An OP counts once its event has begun and its day has come. '
         'OPs of different events on one date count once for each type of event: two meetings on one date are one '
         'OP. They also count once across all types: a meeting and a training on one date are one OP across all '
         'types.'),
        ('Unit OP',
         'An OP attended by at least one member other than the AHC, at an event of that type, counted once a date '
         'as a member\'s are.'
         + (own.format('OP', 'unit OP') if member_report else '')),
        ('Hours',
         "Hours of time logged on events; nothing else counts as hours. Each logged time's hours are shown on the "
         'day or days it counts as (see Day attended).{} When a logged time has hours on a date that does not '
         'count for it, they are added to the nearest date that does{}. No hours are lost this way.'.format(
             example(' 10pm to 4am counts as one day, on the second date, so all 6 hours are shown on that date.'),
             example(': for 8am Saturday to 1am Sunday, all 17 hours are shown on Saturday'))),
        ('Guests',
         'Those whose status today is {}, and members before the day they joined: the date of their {} '
         'endorsement, or with no date, the year its comment starts with; without either, their first training or '
         'operation. A member with none of these has not joined. Time as a guest counts only on their own activity '
         'report.'.format(
             guests, rules.JOINED_ENDORSEMENT)),
        ('OL', 'Operation Leader: marked OL on an entry on the event page.'),
        ('AHC',
         'At Home Coordinator: marked AHC on an entry for an operation on the event page. Time as AHC counts as '
         'days attended, OPs attended and hours, but not as time in the field. A day or an OP counts as AHC only on '
         'a date with no time in the field on an operation.'),
        ('Led',
         'On an operation, in the field as OL. On a training (as TL or LL), a meeting or a community event, named '
         'in its leaders text, as the event page links leaders, or marked OL.'),
        ('Events left out',
         "Events whose titles the team's settings mark as tests or demonstrations aren't counted."
         + (' From {} {:%b %Y}, when pages were first recorded, an operation with no page sent, nobody listed and no '
            'title calling it a heads-up was never used: it isn\'t counted. A page sent with the event page\'s '
            'Test button is no page.'.format(paged_from.day, paged_from)
            if paged_from else '')),
        ('Time left out',
         'More than {} day{} logged by one member for one event or operating period counts one day and no '
         'hours. An event that has not started yet, and a day after today, count nothing yet; hours after the '
         'end of today are left out.'
         .format(rules.MAX_ENTRY_DAYS, pluralize(rules.MAX_ENTRY_DAYS))
         + (" Nothing dated before {}, the first year of the unit's records, counts on this report: a date that "
            'early is taken as mistyped.'.format(records_from.year) if member_report and records_from else '')),
        # The marks on a row of the member report's lists (activity-member.html). The example holds under any day
        # rules, as Sunday is period 1's fullest date, but not where an entry may run no more than a day: period 1
        # would then count no hours.
        *([('† ‡ Hours and days not added',
            "Hours and days in a row of the event lists that the totals don't add are shown after a mark. They are "
            'hours and days like any others, never negative. † marks hours or days counted on another row. Where two '
            'logged times overlap, the hours they share count once, on the row whose time began first. A date counts '
            "once in each type's list, on the row whose time began first: two meetings on one date show 1 and †1. "
            "Each list's days add up to its type's days in the table, whose Total counts a date with more than one "
            'type once, as All does.{} ‡ marks hours left out of the totals, for a reason under Time left out.'.format(
                " For example, period 1 of an operation from 7:56am Saturday to 5:27pm Sunday, and period 2 from 6am "
                "to 4:20pm Sunday: period 2's 10.3 hours all fall within period 1's, and its one day, Sunday, is also "
                "one of period 1's, so both count on period 1's row, and period 2's row shows †10.3 hours and †1 "
                'day.' if rules.MAX_ENTRY_DAYS >= 2 else ''))] if member_report else []),
        ('Y-axis scale',
         'Shared puts every panel of a chart on one scale, so their columns read against each other. Separate '
         "gives each panel its own, so a small panel's columns show their shape."),
    ]
    if member_report:
        terms += [
            ('AHC OPs', 'OPs of operations attended as AHC.'),
            ('DO weeks',
             'Duty Officer weeks. An assigned DO week counts once its shift starts, in the month and year that hold '
             'most of its days; in its first three days, on today.'),
            ('All',
             'Every type of event together. In days and OPs, a date with more than one type counts once, under '
             'the first of Operations, Trainings, Meetings and Community.'),
        ]
    return terms


# The member chart's colours. The panel of every type together shades by
# type, strongest for operations and grey for community events; each type's
# own panel shows the role it was attended in, in three blues, darkest at
# the foot: leading, the attendance not picked out under a role, then AHC.
TYPE_COLOURS = {'operation': '1-strong', 'training': '1', 'meeting': '1-light', 'community': 'muted'}
ROLE_COLOURS = {'led': '1-strong', 'other': '1', 'ahc': '1-light'}
# How the All panel's figures name each type, number first, under a head line that gives the unit ("21 of 51
# days"): the type alone, in lower case and one word, so that a line never wraps in the box ("16 trainings"),
# and in the singular for one event ("1 operation").
TYPE_WORDS = {'operation': 'operations', 'training': 'trainings', 'meeting': 'meetings', 'community': 'community'}
ONE_EVENT = {'operation': 'operation', 'training': 'training', 'meeting': 'meeting', 'community': 'community'}


def _lines(role, amount, hours=False):
    """A line of a column's figures for what was done in a role, if any."""
    return [(charts.hours_text(amount) if hours else amount, 'as ' + role)] if amount else []


def _counted(label, attended, parts, whole, noun, more=()):
    """One column of days, events or OPs, against the unit's, and its figures
    with the unit's figures switched off. Parts are (colour, amount); `more`
    is further lines for its figures."""
    return {'parts': parts, 'total': whole,
            'tip': [label, ('{} of {}'.format(attended, whole), noun + pluralize(whole)), *more],
            'tip_without_total': [label, (attended, noun + pluralize(attended)), *more]}


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
    """A type's own panel, as OPs, days, events and hours: the same colours
    whatever the type, with what was led (as OL, or as TL or LL) picked out
    at the foot of the column, where it can be compared from one period to
    the next."""
    days, events, ops = r.days[event_type], r.events[event_type], r.ops[event_type]
    active_days, unit_events, unit_ops = r.active_days[event_type], r.unit_events[event_type], r.unit_ops[event_type]
    other_hours = r.other_hours[event_type]
    if event_type == 'operation':
        ol, ahc = r.ol_days, r.ahc_days
        return [_counted(label, ops, _by_role(r.ol_ops, ops - r.ol_ops - r.ahc_ops, r.ahc_ops), unit_ops, 'OP',
                         _lines(LEADING['operation'], r.ol_ops) + _lines('AHC', r.ahc_ops)),
                _counted(label, days, _by_role(ol, days - ol - ahc, ahc), active_days, 'day',
                         _lines(LEADING['operation'], ol) + _lines('AHC', ahc)),
                _counted(label, events, _by_role(r.ol_events, events - r.ol_events - r.ahc_events, r.ahc_events),
                         unit_events, 'event', _lines(LEADING['operation'], r.ol_events) + _lines('AHC', r.ahc_events)),
                _logged(label, _by_role(r.ol_hours, other_hours, r.ahc_hours),
                        _lines(LEADING['operation'], r.ol_hours, hours=True) + _lines('AHC', r.ahc_hours, hours=True))]
    led, led_events, led_ops = r.led_days[event_type], r.led_events[event_type], r.led_ops[event_type]
    led_hours, role = r.led_hours[event_type], LEADING[event_type]
    return [_counted(label, ops, _by_role(led_ops, ops - led_ops), unit_ops, 'OP', _lines(role, led_ops)),
            _counted(label, days, _by_role(led, days - led), active_days, 'day', _lines(role, led)),
            _counted(label, events, _by_role(led_events, events - led_events), unit_events, 'event',
                     _lines(role, led_events)),
            _logged(label, _by_role(led_hours, other_hours), _lines(role, led_hours, hours=True))]


def _all_cells(label, r):
    """Every type in one column, shaded by type, with a line of its figures
    for each type it draws, from the foot up: a day, or a day's OPs, under
    the first type attended on it, as the column counts it."""
    def by_type(amounts):
        return [(TYPE_COLOURS[t], amounts[t]) for t in TYPES]

    def lines(amounts, hours=False):
        return [(charts.hours_text(amounts[t]) if hours else amounts[t], TYPE_WORDS[t]) for t in TYPES if amounts[t]]

    def events(amounts):
        return [(amounts[t], ONE_EVENT[t] if amounts[t] == 1 else TYPE_WORDS[t]) for t in TYPES if amounts[t]]
    return [_counted(label, r.all_ops, by_type(r.first_ops), r.all_unit_ops, 'OP', lines(r.first_ops)),
            _counted(label, r.all_days, by_type(r.first_days), r.all_active_days, 'day', lines(r.first_days)),
            _counted(label, sum(r.events.values()), by_type(r.events), sum(r.unit_events.values()), 'event',
                     events(r.events)),
            _logged(label, by_type(r.hours), lines(r.hours, hours=True))]


def _keys(total):
    """The key under each type's panel: the colours its columns draw, in any
    period, which are those the whole of the member's record draws, in the
    order they stack from the foot, each named. Attendance is "as
    participant" beside a role picked out, and "Attended" alone, as it is too
    for a panel that draws nothing."""
    order = (ROLE_COLOURS['led'], ROLE_COLOURS['other'], ROLE_COLOURS['ahc'])
    keys = {}
    for t in TYPES:
        drawn = {colour for column in _type_cells('', total, t) for colour, amount in column['parts'] if amount}
        names = {ROLE_COLOURS['led']: 'as ' + LEADING[t], ROLE_COLOURS['ahc']: 'as AHC',
                 ROLE_COLOURS['other']: 'as participant' if drawn - {ROLE_COLOURS['other']} else 'Attended'}
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


def _cell(days, ops, hours):
    """A table cell, "days / OPs / hours": the hours to one decimal, as the
    event lists show them, so that the rows add up to the total; blank with
    none of the three."""
    return '{} / {} / {}'.format(days, ops, charts.hours_text(hours)) if days or ops or charts.hours_tenths(hours) else ''


def _table(years, total):
    """The table: one column per type as "days / OPs / hours", with a count
    of OPs beside it for each of its duties the member has done, and DO
    weeks, and a row for each year, of [(label, short, row)], and the total."""
    duties = {'operation': (('OL OPs', lambda r: r.ol_ops), ('AHC OPs', lambda r: r.ahc_ops),
                            ('DO weeks', lambda r: r.do_days)),
              'training': (('{} OPs'.format(LEADING['training']), lambda r: r.led_ops['training']),)}
    columns = []
    for t, label in EVENT_TYPES:
        columns.append((label, lambda r, t=t: _cell(r.days[t], r.ops[t], r.hours[t])))
        columns += [(duty_label, lambda r, count=count: count(r) or '')
                    for duty_label, count in duties.get(t, ()) if count(total)]
    columns.append(('Total', lambda r: _cell(r.all_days, r.all_ops, r.all_hours)))

    def table_row(label, r):
        # Each cell with its column's heading, for a screen too narrow for columns.
        return {'label': label, 'cells': [(heading, value(r)) for heading, value in columns]}

    return {
        'title': 'Days attended / OPs attended / hours logged',
        'columns': [heading for heading, _ in columns],
        'counts': {heading for kinds in duties.values() for heading, _ in kinds},
        'rows': [table_row(label, r) for label, _, r in years],
        'total': table_row('Total', total),
    }


def member_activity(member, now, entries, since, hours=None, unit=None):
    """The chart and table of a member's activity, for their activity report,
    from their entries (member_entries), counted from `since` (records_from)
    on, with the hours each counts for (counting.counted_hours) and what the
    unit did (counting.activity_rows' `unit`) if read already. Returns None
    when there is nothing to show."""
    rows = activity_rows(member, now, entries, since, hours, unit)
    if rows is None:
        return None
    keys = _keys(rows['total'])
    years, months, span = _periods(rows)
    chart = charts.share_panels(
        [{'label': 'OPs', 'total_label': 'Unit OPs',
          'title': 'OPs attended / unit OPs, by type and role, ' + span,
          'title_without_total': 'OPs attended, by type and role, ' + span},
         {'label': 'Days', 'total_label': 'Unit active days',
          'title': 'Days attended / unit active days, by type and role, ' + span,
          'title_without_total': 'Days attended, by type and role, ' + span},
         {'label': 'Events', 'total_label': 'Unit events',
          'title': 'Events attended / unit events, by type and role, ' + span,
          'title_without_total': 'Events attended, by type and role, ' + span},
         {'label': 'Hours', 'title': 'Hours logged, by type and role, ' + span}],
        [_view('Years', years, keys), _view('Months', months, keys)],
        note="How many OPs, days and events does this member attend, against the unit's, and how many hours do they "
             "log?",
        note_without_total='How many OPs, days and events does this member attend, and how many hours do they log?',
        name='activity', measure_switch_label='Count', total_switch_label='Unit figures')
    return {'chart': chart, 'table': _table(years, rows['total'])}
