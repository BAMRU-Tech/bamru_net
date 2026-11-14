"""Build the structures the chart templates in templates/charts/ draw.

Views and report code produce numbers; the functions here turn them into
marks (sizes, ticks, labels); the templates draw them; static/css/charts.css
holds every colour and size.

A chart is a function in its report's module that returns share_panels(...)
or with_menu(...), with colours from COLOURS and a name of its own on the
page. The page includes charts/share_panels.html with the chart, and loads
css/charts.css and, deferred, js/charts.js. Breakpoints and the names the
templates, stylesheet and script share are checked by tests/test_charts.py.

Columns run left to right in the order given: periods of time, or categories.
"""
import math
import re
from decimal import ROUND_HALF_UP, Decimal

from django.template.defaultfilters import floatformat


# The most measures and views a chart has, one switch each.
MAX_MEASURES = 3
MAX_VIEWS = 3


def axis_top(largest):
    """The smallest round number at or above the largest value whose half is
    a whole number, so the axis has clean ticks at the top and the middle.
    The value is first rounded far past what a chart shows, so that a sum's
    floating-point error (20.000000000000004) does not lift the axis a step."""
    largest = round(largest, 6)
    if largest <= 2:
        return 2
    power = 10 ** math.floor(math.log10(largest))
    for step in (1, 1.2, 1.5, 2, 3, 4, 5, 6, 8, 10):
        top = step * power
        if top >= largest and top % 2 == 0:
            return int(top)


def _percent(value, whole):
    """`value` as a percentage of `whole`, to two places, and, when it is not
    nothing, never rounded to nothing: the stylesheet draws any size above
    zero as at least a hairline, so a column far below the largest still shows."""
    if not whole:
        return 0
    share = round(100 * value / whole, 2)
    return share if share or not value else math.copysign(0.01, value)


def _below(cell):
    """How far a cell's parts reach below zero."""
    return -sum(value for _, value in cell['parts'] if value < 0)


def _scale(cells, m):
    """The value axis for these cells in measure m: (top, floor, step). The
    floor is how far the axis runs below zero, 0 when nothing does."""
    up = max((max(c[m]['total'], c[m].get('marker') or 0) for c in cells), default=0)
    down = max((max(_below(c[m]), -(c[m].get('marker') or 0)) for c in cells), default=0)
    if not down:
        top = axis_top(up)
        return top, 0, top // 2
    # One step above and below zero, so the gridlines are evenly spaced.
    step = axis_top(max(up, down)) // 2
    return math.ceil(up / step) * step, math.ceil(down / step) * step, step


def _sizes(amounts, scales, above):
    """Each measure's amount as a share of its axis above zero, or below it,
    on each of a panel's scales, {'own': axes, 'shared': axes} as _scale
    gives them: {'own': [...], 'shared': [...]}."""
    return {which: [_percent(amount, top if above else floor) for amount, (top, floor, _) in zip(amounts, axes)]
            for which, axes in scales.items()}


def _ticks(top, floor, step):
    ticks = [{'value': value, 'at': _percent(value + floor, top + floor)}
             for value in range(top, -floor - 1, -step)]
    for tick in ticks:
        if tick['value'] == 0:
            tick['base'] = True
    return ticks


def _colour(name):
    """A colour name as the class that draws it and, for a step of the ramp,
    how far along the ramp it is (a percentage)."""
    if name.startswith('ramp-'):
        _, step, steps = name.split('-')
        return {'colour': 'ramp', 'ramp': _percent(int(step) - 1, int(steps) - 1)}
    return {'colour': name}


# The colours a part may have: a chart-part-... class in charts.css each.
COLOURS = {'1', '1-strong', '1-light', '1-pale', '2', '2-light', 'muted', 'muted-light', 'total'}


def _fail(where, message):
    """Refuse a chart's input: ValueError, saying where, from the chart's name
    to the place in it, then what is wrong."""
    name, *places = where
    raise ValueError('chart {!r}{}: {}'.format(name, ''.join(', ' + place for place in places), message))


def _check_colour(colour, where, key=False):
    """A colour is one of COLOURS, a step of the ramp, or, in a key, 'marker'."""
    ramp = re.fullmatch(r'ramp-(\d+)-(\d+)', colour)
    if not (colour in COLOURS or (key and colour == 'marker')
            or (ramp and 1 <= int(ramp[1]) <= int(ramp[2]) and int(ramp[2]) > 1)):
        _fail(where, '{!r} is not a colour the charts have'.format(colour))


def _check(name, measures, views):
    """Raise ValueError, saying where, for input share_panels would draw wrongly
    or fail on later with an error that does not say what is wrong."""
    for measure in measures:
        if 'label' not in measure or 'title' not in measure:
            _fail((name,), 'a measure has a label and a title')
    for view in views:
        if any(key not in view for key in ('label', 'periods', 'series')):
            _fail((name,), 'a view has a label, periods and series')
        _check_view(view, measures, (name, 'view {!r}'.format(view['label'])))


def _check_view(view, measures, where):
    """A view's periods, titles and panels."""
    if any(not isinstance(period.get('short'), str) for period in view['periods']):
        _fail(where, "every period has a short label, '' for none")
    if view.get('max_labels', 9) < 1:
        _fail(where, 'max_labels is at least 1')
    titles = view.get('titles', measures)
    if not (isinstance(titles, (list, tuple)) and len(titles) == len(measures)):
        _fail(where, 'a view with titles has a list of them, one for each measure')
    for series in view['series']:
        _check_panel(series, len(view['periods']), measures, where + ('panel {!r}'.format(series.get('label', '')),))


def _check_panel(series, periods, measures, where):
    """A panel's key, and a column for each of the view's periods."""
    if not series.get('key'):
        _fail(where, 'every panel has a key: name what its columns count')
    if 'cells' not in series:
        _fail(where, 'every panel has cells')
    for item in series['key']:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            _fail(where + ('key',), 'a key names its items as (colour, label)')
        _check_colour(item[0], where + ('key',), key=True)
    if (any('marker' in entry for cell in series['cells'] for entry in cell)
            and 'marker' not in [colour for colour, _ in series['key']]):
        _fail(where, "a panel with markers names them in its key, as 'marker'")
    if len(series['cells']) != periods:
        _fail(where, '{} columns for {} periods'.format(len(series['cells']), periods))
    for i, cell in enumerate(series['cells']):
        _check_column(cell, measures, where + ('column {}'.format(i + 1),))


def _check_column(cell, measures, where):
    """A column's entries, one for each measure: their figures, tips and parts,
    the same colours in the same order in each."""
    if len(cell) != len(measures):
        _fail(where, 'a column has one entry for each measure')
    for entry in cell:
        if any(key not in entry for key in ('parts', 'total', 'tip')):
            _fail(where, 'a column has parts, a total and a tip for each measure')
        if len(measures) > 1 and ('marker' in entry or any(value < 0 for _, value in entry['parts'])):
            _fail(where, 'markers and parts below zero are for a chart of one measure')
        figures = [entry['total'], entry.get('marker') or 0] + [value for _, value in entry['parts']]
        if any(not isinstance(figure, (int, float)) or math.isnan(figure) for figure in figures):
            _fail(where, 'every figure is a number')
        tip = entry['tip']
        if not (isinstance(tip, str) or isinstance(tip, (list, tuple)) and all(
                isinstance(line, str) or isinstance(line, (list, tuple)) and len(line) == 2 for line in tip)):
            _fail(where, 'a tip is a line, or a list of a heading and lines, each text or (number, label)')
    colours = [colour for colour, _ in cell[0]['parts']]
    if len(set(colours)) != len(colours):
        _fail(where, 'a colour is used twice in one column')
    for colour in colours:
        _check_colour(colour, where)
    for entry in cell:
        if [colour for colour, _ in entry['parts']] != colours:
            _fail(where, 'the measures list different colours, or the same in another order')
        if entry['total'] < 0:
            _fail(where, 'a total is not below zero; parts below zero are parts')
        reached = sum(value for _, value in entry['parts'] if value > 0)
        if reached > entry['total'] * (1 + 1e-9) + 1e-9:
            _fail(where, 'the parts above zero add up to {}, more than the total {}'.format(reached, entry['total']))


def _tip(tip):
    """A column's figures as a heading and the lines under it. A line is
    (number, label), drawn number first with the numbers in a column, or
    plain text."""
    lines = [tip] if isinstance(tip, str) else list(tip)
    return {'head': lines[0] if lines else '',
            'lines': [{'text': line} if isinstance(line, str) else {'number': line[0], 'label': line[1]}
                      for line in lines[1:]]}


def _tip_at(i, n):
    """Where column i of n's figures float, so that they stay within the
    plot's width: from the column's left edge in the left third, centred on
    it in the middle, back from its right edge in the right third."""
    middle = (i + 0.5) / n
    if middle < 1 / 3:
        return {'side': 'left', 'at': round(100 * i / n, 2)}
    if middle > 2 / 3:
        return {'side': 'right', 'at': round(100 * (n - 1 - i) / n, 2)}
    return {'side': 'centre', 'at': round(100 * middle, 2)}


def hours_tenths(hours):
    """Hours as the reports write them (hours_text), as a number: to one
    decimal, half up as written, so an hour and a quarter is 1.3. Rounded far
    past the tenth first, so that a sum's floating-point error (27.55 added up
    as 27.549999...) does not tip it. A Decimal, for deciding what to write
    whatever the language writes a tenth in (the template filter
    `hours_tenths`): zero when the hours are written as nothing."""
    return Decimal(str(round(hours, 6))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def hours_text(hours):
    """Hours as the reports write them, in tables, charts and an entry's row
    (the template filter `hours`): hours_tenths, with thousands grouped:
    '1,234.5'."""
    return floatformat(hours_tenths(hours), '1g')


def year_label(year):
    """A year as a chart's time axis shows it: "'24"."""
    return "'{:02d}".format(year % 100)


def _in_drawn_order(measures, views, start_measure):
    """(switch, measures, views): the measures, and each view's titles and
    cells, in the order they are drawn, with the one started on
    (`start_measure`, a label; the first if None) first, which charts.css
    shows without the switch; and the switch, the measures in the order
    given, each with its number as drawn."""
    labels = [measure['label'] for measure in measures]
    if start_measure is not None and start_measure not in labels:
        raise ValueError('a chart starts on one of its measures, {}: {!r}'.format(', '.join(labels), start_measure))
    first = labels.index(start_measure) if start_measure else 0
    order = [first] + [m for m in range(len(measures)) if m != first]
    return ([dict(measure, number=order.index(m) + 1) for m, measure in enumerate(measures)],
            [measures[m] for m in order],
            [dict(view, titles=view.get('titles') and [view['titles'][m] for m in order],
                  series=[dict(s, cells=[[cell[m] for m in order] for cell in s['cells']]) for s in view['series']])
             for view in views])


def share_panels(measures, views, note='', *, name, start_measure=None, measure_switch_label='Show',
                 view_switch_label='By'):
    """Columns by period or category, one small panel per series. Each column is a total
    (pale) with the parts reached stacked inside it, bottom up.

    measures: one to three things to plot on the same columns, in the order
      of the switch:
      {'label': 'Days', 'title': ..., 'total_label': 'Unit active'}
      total_label names the pale part in the legend; leave it out when the
      parts always add up to the total. The note keeps room for the longest,
      so that it does not reflow when the measure changes.
    views: up to three ways of drawing it, the first shown by default: usually
      ways of cutting time, named for the reader by view_switch_label.
      {'label': 'Years', 'name': ..., 'max_labels': 9, 'titles': [...],
       'periods': [{'short': ...}],                              # oldest first
       'series': [{'label': ..., 'key': [(colour, label), ...],
                   'cells': [[{'parts': [(colour, value), ...],
                               'total': ..., 'tip': ..., 'marker': ...}, ...]]}]}
      key names a panel's colours under it, and every panel has one, even
      of a single colour: [('1', 'Pages')]. A series may have an empty
      label, for a chart of one panel whose title already says what it is.
      name, which may be left out, is what a screen reader is told each of
      the view's plots is, after its series label, in place of the view's
      label: for a label that does not say it alone, such as 'Month'.
      short goes on the time axis, and may be empty for an unlabelled period.
      titles, one per measure, replace the measures' titles while that view
      is shown; leave it out when the measures' titles hold for every view.
      Each cell is a list with one entry per measure. tip is the figures
      shown by the column under the pointer or tapped: a line, or a list
      of lines, the first a heading and the rest (number, label) pairs,
      such as (5, 'joined'), or plain text. Its parts stack bottom
      up in the order given, and must be in the same order in every measure.
      On a chart of one measure, a part with a negative value hangs below
      zero, and those stack downward in the order given; the total is the
      whole above zero only. marker, which may be left out, is a value marked
      on the column of a chart of one measure with a small dark dot (a net,
      say); name it in the key with the colour 'marker'.
    A colour is the name of a chart-part-... class in charts.css: '1' and '2'
      for the series colours, '1-strong' and '1-light' for a darker and a
      lighter step of the first, '2-light' for a lighter step of the second,
      'muted' for grey, 'muted-light' a lighter grey between it and the
      total, for a second kind of what is not attendance. '1-pale' is a fourth, palest blue for ordered steps
      ('1-pale', '1-light', '1', '1-strong'); it is close to the pale total,
      so not for a column that shows one. For more layers than four,
      'ramp-3-17' is step 3 of 17 from '1-pale' through '1' at the middle
      to '1-strong'.
    start_measure: the label of the measure shown to start with, and in a
      browser without the switches; the first if left out. The switch keeps
      the order of measures.
    note: a sentence under the title saying what the chart is for; terms
      are defined in the report's glossary, not here.
    measure_switch_label, view_switch_label: the words drawn before each
      switch, saying what it sets ('Show', 'By', or 'Left after no activity
      for'); '' leaves one without. The scale's switch says 'Scale'.
    name: this chart's own on the page, a letter and then letters, digits,
      hyphens or underscores; it ties the switches and the title to it.

    A chart of several panels starts on the scale they share, and its scale
    switch gives each panel its own; a chart of one panel has no such switch.

    Every size is worked out for both scales, so the reader can switch.
    """
    if not re.fullmatch(r'[A-Za-z][\w-]*', name, re.ASCII):
        raise ValueError('a chart\'s name is a letter, then letters, digits, - or _: {!r}'.format(name))
    if not 1 <= len(measures) <= MAX_MEASURES or not 1 <= len(views) <= MAX_VIEWS:
        raise ValueError('share_panels draws one to {} measures and one to {} views'.format(MAX_MEASURES, MAX_VIEWS))
    _check(name, measures, views)
    switch, measures, views = _in_drawn_order(measures, views, start_measure)
    numbers = range(len(measures))
    drawn = []
    for v, view in enumerate(views):
        periods = view['periods']
        labelled = [i for i, p in enumerate(periods) if p['short']]
        step = math.ceil(len(labelled) / view.get('max_labels', 9)) if labelled else 1
        shown = set(labelled[::-1][::step])
        every = [c for s in view['series'] for c in s['cells']]
        shared_scales = [_scale(every, m) for m in numbers]
        panels = []
        for s in view['series']:
            scales = {'own': [_scale(s['cells'], m) for m in numbers], 'shared': shared_scales}
            signed = any(floor for which in scales.values() for _, floor, _ in which)
            cells = []
            for i, c in enumerate(s['cells']):
                colours = [colour for colour, _ in c[0]['parts']]      # the same in every measure (_check)
                values = {colour: [dict(c[m]['parts'])[colour] for m in numbers] for colour in colours}
                below = [_below(c[m]) for m in numbers]
                parts, under = [], []
                for colour in colours:
                    up = [_percent(max(value, 0), c[m]['total']) for m, value in enumerate(values[colour])]
                    down = [_percent(max(-value, 0), below[m]) for m, value in enumerate(values[colour])]
                    if any(up):
                        parts.append(dict(_colour(colour), sizes=up))
                    if any(down):
                        under.append(dict(_colour(colour), sizes=down))
                cell = {
                    'drawn': any(c[m]['total'] for m in numbers),
                    'tips': [_tip(c[m]['tip']) for m in numbers],
                    'tip_at': _tip_at(i, len(s['cells'])),
                    'parts': parts,
                }
                cell.update(_sizes([c[m]['total'] for m in numbers], scales, above=True))
                if under:
                    cell['under'] = dict(_sizes(below, scales, above=False), parts=under)
                if c[0].get('marker') is not None:
                    # Where the dot sits, as a share of the whole axis, floor to top, on each
                    # scale; markers are for a chart of one measure (_check).
                    cell['marker'] = {which: _percent(c[0]['marker'] + floor, top + floor)
                                      for which, ((top, floor, _),) in scales.items()}
                cells.append(cell)
            panels.append({
                'label': s.get('label', ''),
                # For readers who cannot see the plot: which panel and view this
                # is. The chart itself is named by its title as shown.
                'name': ', '.join(part for part in (s.get('label'), view.get('name') or view['label']) if part),
                'key': [dict(_colour(colour), label=label) for colour, label in s['key']],
                'ticks': [{'measure': m + 1, 'scale': which, 'ticks': _ticks(*scales[which][m])}
                          for m in numbers for which in ('own', 'shared')],
                # With parts below zero, which a chart of one measure may have (_check), the
                # share of the plot above zero on each scale.
                'signed': signed and {which: round(top / (top + floor), 4)
                                      for which, ((top, floor, _),) in scales.items()},
                'cells': cells,
            })
        drawn.append({
            'label': view['label'],
            'number': v + 1,
            'axis': [{'label': p['short'], 'shown': i in shown} for i, p in enumerate(periods)],
            'panels': panels,
        })
    return {
        'titles': [{'measure': m + 1, 'view': v + 1,
                    'text': view['titles'][m] if view.get('titles') else measure['title']}
                   for v, view in enumerate(views) for m, measure in enumerate(measures)],
        'scale_switch': any(len(view['series']) > 1 for view in views),
        'view_switch_label': view_switch_label,
        'measure_switch_label': measure_switch_label,
        'measures': switch,
        # The keys to the measures' totals, in the note: one place for them all.
        'total_keys': [{'number': m + 1, 'label': measure['total_label']}
                       for m, measure in enumerate(measures) if measure.get('total_label')],
        'note': note,
        'name': name,
        'views': drawn,
        # The longest value on any value axis, in characters: the gutter is made wide enough for it.
        'digits': max((len(str(tick['value'])) for view in drawn for panel in view['panels']
                       for ticks in panel['ticks'] for tick in ticks['ticks']), default=1),
    }


def with_menu(options, label):
    """One chart whose figures the reader changes from a menu among its
    controls, under the plots, for more choices than a switch holds (a
    year, say). options is [(label, chart)], in the menu's order, each chart
    drawn by share_panels with the same name, measures (started on the same
    one), views and switches,
    so that one set of switches serves them all; the first is the one shown
    to start with, and without script. The page needs js/charts.js: every
    option's title and plots are in the page, and the script puts the one
    chosen in place."""
    if not options:
        raise ValueError('with_menu needs options')
    if len({chart['name'] for _, chart in options}) > 1:
        raise ValueError('the charts of one menu share one name')
    if len({(tuple((measure['label'], measure['number']) for measure in chart['measures']),
             tuple(view['label'] for view in chart['views']),
             chart['scale_switch']) for _, chart in options}) > 1:
        raise ValueError('the charts of one menu have the same measures and views, which the switches serve')
    chart = dict(options[0][1])
    # Every option's titles are laid out unseen in the title's place, so that
    # the head is as tall for one option as for another and nothing moves.
    sizes = list(dict.fromkeys(title['text'] for _, option_chart in options for title in option_chart['titles']))
    chart['digits'] = max(option_chart['digits'] for _, option_chart in options)
    chart['menu'] = {'label': label, 'title_sizes': sizes,
                     'options': [{'label': option_label, 'chart': option_chart, 'selected': i == 0}
                                 for i, (option_label, option_chart) in enumerate(options)]}
    return chart
