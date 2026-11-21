import re

from django.contrib.staticfiles import finders
from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase, TestCase

from main.lib import charts
from main.lib.charts import axis_top, with_menu


def share_panels(*args, name='chart', **options):
    """charts.share_panels, with a name for the tests that are not about it."""
    return charts.share_panels(*args, name=name, **options)


class ChartsTestCase(TestCase):
    def test_axis_top(self):
        self.assertEqual([axis_top(n) for n in (0, 1, 3, 7, 13, 38, 54, 96, 103)],
                         [2, 2, 4, 8, 20, 40, 60, 100, 120])
        # Hours added up in floating point top the axis where their sum does.
        self.assertEqual(axis_top(0.1 * 3 * 66.66666666666667), 20)

    MEASURES = [{'label': 'Days', 'title': 'Days'}]

    def view(self, cells_by_series, periods=None, key=(('1', 'Counted'),), **options):
        """Cells are (part, ..., total) for a single measure."""
        count = len(cells_by_series[0])
        periods = periods or [{'short': str(n)} for n in range(count)]
        series = [{'label': 'S', 'key': key,
                   'cells': [[{'parts': list(zip('12', parts)), 'total': total, 'tip': 'tip'}]
                                           for *parts, total in cells]}
                  for cells in cells_by_series]
        return dict({'label': 'View', 'periods': periods, 'series': series}, **options)

    def test_share_panels(self):
        chart = share_panels(self.MEASURES, [self.view([[(5, 10), (5, 5, 20), (0, 0)]], key=[('1', 'A'), ('2', 'B')])])
        panel = chart['views'][0]['panels'][0]
        own, shared = panel['ticks']
        self.assertEqual([t['value'] for t in own['ticks']], [20, 10, 0])
        self.assertEqual((own['scale'], shared['scale'], shared['ticks']), ('own', 'shared', own['ticks']))
        one, two, none = panel['cells']
        self.assertEqual((one['own'], one['parts']), ([50], [{'colour': '1', 'sizes': [50]}]))
        self.assertEqual((two['own'], two['parts']),
                         ([100], [{'colour': '1', 'sizes': [25]}, {'colour': '2', 'sizes': [25]}]))
        self.assertEqual((none['drawn'], none['parts']), (False, []))
        self.assertEqual(panel['key'], [{'colour': '1', 'label': 'A'}, {'colour': '2', 'label': 'B'}])

    def test_two_measures(self):
        cells = [[{'parts': [('1', 5), ('2', 0)], 'total': 10, 'tip': 'days'},
                  {'parts': [('1', 30), ('2', 10)], 'total': 40, 'tip': 'hours'}]]
        view = {'label': 'View', 'periods': [{'short': '1'}],
                'series': [{'key': [('1', 'Counted')], 'label': 'S', 'cells': cells}]}
        chart = share_panels(self.MEASURES + [{'label': 'Hours', 'title': 'Hours'}], [view])
        cell = chart['views'][0]['panels'][0]['cells'][0]
        self.assertEqual(cell['tips'], [{'head': 'days', 'lines': []}, {'head': 'hours', 'lines': []}])
        self.assertEqual(cell['own'], [100, 100])
        self.assertEqual(cell['parts'], [{'colour': '1', 'sizes': [50, 75]}, {'colour': '2', 'sizes': [0, 25]}])
        self.assertEqual([(t['measure'], t['scale']) for t in chart['views'][0]['panels'][0]['ticks']],
                         [(1, 'own'), (1, 'shared'), (2, 'own'), (2, 'shared')])

    def test_titles_and_switches(self):
        measures = self.MEASURES + [{'label': 'Hours', 'title': 'Hours'}]
        cell = [[{'parts': [('1', 1)], 'total': 1, 'tip': ''}] * 2]
        period = [{'short': '1'}]
        one = {'label': 'Unit', 'periods': period, 'series': [{'key': [('1', 'Counted')], 'label': 'S', 'cells': cell}]}
        two = dict(one, label='People', titles=['People-days', 'People-hours'],
                   series=[{'key': [('1', 'Counted')], 'label': 'S', 'cells': cell}, {'key': [('1', 'Counted')], 'label': 'T', 'cells': cell}])
        chart = share_panels(measures, [one, two], view_switch_label='Count')
        self.assertEqual([(t['measure'], t['view'], t['text']) for t in chart['titles']],
                         [(1, 1, 'Days'), (2, 1, 'Hours'), (1, 2, 'People-days'), (2, 2, 'People-hours')])
        self.assertEqual((chart['scale_switch'], chart['view_switch_label']), (True, 'Count'))
        # A single panel has no scale switch.
        self.assertFalse(share_panels(measures, [one])['scale_switch'])

    def test_four_measures_at_most(self):
        labels = ['Days', 'Events', 'OPs', 'Hours', 'Miles']
        measures = [{'label': label, 'title': label} for label in labels]
        cell = [{'parts': [('1', n)], 'total': 10, 'tip': label} for n, label in enumerate(labels, 1)]
        view = {'label': 'Years', 'periods': [{'short': "'24"}],
                'series': [{'key': [('1', 'Counted')], 'label': 'Operations', 'cells': [cell[:4]]}]}
        chart = share_panels(measures[:4], [view], measure_switch_label='Count')
        self.assertEqual([(m['label'], m['number']) for m in chart['measures']],
                         [('Days', 1), ('Events', 2), ('OPs', 3), ('Hours', 4)])
        self.assertEqual(chart['measure_switch_label'], 'Count')
        self.assertEqual(chart['views'][0]['panels'][0]['cells'][0]['parts'][0]['sizes'], [10, 20, 30, 40])
        with self.assertRaises(ValueError):
            share_panels(measures, [dict(view, series=[dict(view['series'][0], cells=[cell])])])

    def test_three_views_and_an_unnamed_panel(self):
        def view(label, tips):
            cells = [[{'parts': [('1', 1)], 'total': 1, 'tip': tip}] for tip in tips]
            return {'label': label, 'titles': [label + ' title'],
                    'periods': [{'short': str(n)} for n in range(len(tips))],
                    'series': [{'key': [('1', 'Counted')], 'label': '', 'cells': cells}]}
        chart = share_panels(self.MEASURES, [view('Month', ['short', 'the longest of these']),
                                             view('Weekday', ['a']), view('Hour', ['b'])])
        self.assertEqual([v['number'] for v in chart['views']], [1, 2, 3])
        self.assertEqual([(t['view'], t['text']) for t in chart['titles']],
                         [(1, 'Month title'), (2, 'Weekday title'), (3, 'Hour title')])
        panel = chart['views'][0]['panels'][0]
        # For those who cannot see it, a plot is named by its panel and view;
        # the chart is named by the title showing.
        self.assertEqual((panel['label'], panel['name']), ('', 'Month'))
        labelled = share_panels(self.MEASURES, [self.view([[(1, 2)]])])
        self.assertEqual(labelled['views'][0]['panels'][0]['name'], 'S, View')
        # A view may give its plots a fuller name than its label.
        named = share_panels(self.MEASURES, [{**self.view([[(1, 2)]]), 'name': 'Pages by year'}])
        self.assertEqual((named['views'][0]['label'], named['views'][0]['panels'][0]['name']), ('View', 'S, Pages by year'))
        html = render_to_string('charts/share_panels.html', {'chart': labelled})
        self.assertIn('<figure class="chart" aria-labelledby="chart-title"', html)
        self.assertIn('id="chart-title"', html)
        self.assertIn('role="group" aria-label="S, View"', html)
        # Each plot is one stop for the Tab key, with or without the script; its columns are reached from it.
        self.assertIn('role="group" aria-label="S, View" tabindex="0"', html)
        self.assertIn('<div class="chart-band" role="listitem" tabindex="-1">', html)
        # The axis's values are not read out among the figures.
        self.assertIn('chart-baseline" aria-hidden="true"', html)
        # A switch is named by the words drawn before it, once.
        two = render_to_string('charts/share_panels.html', {'chart': share_panels(
            self.MEASURES, [self.view([[(1, 2)]]), self.view([[(1, 2)]])], view_switch_label='By')})
        self.assertIn('<span class="chart-control-label" id="chart-view-label">By</span>', two)
        self.assertIn('role="radiogroup" aria-labelledby="chart-view-label"', two)
        self.assertNotIn('aria-label="By"', two)
        self.assertIn('role="radiogroup" aria-label="View"', render_to_string('charts/share_panels.html', {
            'chart': share_panels(self.MEASURES, [self.view([[(1, 2)]]), self.view([[(1, 2)]])], view_switch_label='')}))
        self.assertEqual(len(share_panels(self.MEASURES, [view(str(n), ['a']) for n in range(4)])['views']), 4)
        with self.assertRaises(ValueError):
            share_panels(self.MEASURES, [view(str(n), ['a']) for n in range(5)])

    def test_figures_as_a_list(self):
        cells = [[{'parts': [('1', 1)], 'total': 1, 'tip': tip}]
                 for tip in (['2024', ('3 of 5', 'days'), (1, 'as OL'), 'so far'], '2025: nothing', [], ['a'], ['b'], ['c'])]
        chart = share_panels(self.MEASURES, [{'label': 'Years', 'periods': [{'short': str(n)} for n in range(6)],
                                              'series': [{'key': [('1', 'Counted')], 'label': 'Operations', 'cells': cells}]}],
                             note='How often?')
        drawn = chart['views'][0]['panels'][0]['cells']
        # A list is a heading and the lines under it, number first; a plain line still works.
        self.assertEqual(drawn[0]['tips'], [{'head': '2024', 'lines': [{'number': '3 of 5', 'label': 'days'},
                                                                       {'number': 1, 'label': 'as OL'},
                                                                       {'text': 'so far'}]}])
        self.assertEqual(drawn[1]['tips'], [{'head': '2025: nothing', 'lines': []}])
        self.assertEqual(drawn[2]['tips'], [{'head': '', 'lines': []}])
        # The figures float from the column's left edge, its middle or its right edge, to stay within the plot.
        self.assertEqual([c['tip_at'] for c in drawn],
                         [{'side': 'left', 'at': 0}, {'side': 'left', 'at': 16.67}, {'side': 'centre', 'at': 41.67},
                          {'side': 'centre', 'at': 58.33}, {'side': 'right', 'at': 16.67}, {'side': 'right', 'at': 0}])

    def test_a_key_item_can_be_for_one_measure_alone(self):
        # Named by the measure's label, it takes that measure's number, which charts.css shows it with.
        cells = [[{'parts': [('1', 1)], 'total': 1, 'tip': ''}, {'parts': [('1', 2)], 'total': 2, 'tip': ''}]]
        view = {'label': 'Years', 'periods': [{'short': '1'}],
                'series': [{'label': '', 'key': [('1', 'Counted'), ('muted-light', 'Others', 'Both')], 'cells': cells}]}
        measures = [{'label': 'Some', 'title': 'Some'}, {'label': 'Both', 'title': 'Both'}]

        def keys(chart):
            return [(k['label'], k.get('measure')) for k in chart['views'][0]['panels'][0]['key']]
        chart = share_panels(measures, [view], name='c')
        self.assertEqual(keys(chart), [('Counted', None), ('Others', 2)])
        html = render_to_string('charts/share_panels.html', {'chart': chart})
        self.assertIn('<span class="chart-key"><i class="chart-part-1"></i>Counted</span>', html)
        self.assertIn('<span class="chart-key chart-key-m2"><i class="chart-part-muted-light"></i>Others</span>', html)
        with self.assertRaisesRegex(ValueError, "the measure's label"):
            share_panels(measures, [dict(view, series=[dict(view['series'][0], key=[('1', 'Counted', 'Neither')])])],
                         name='c')

    def test_menu(self):
        def chart(period, name='ops'):
            cells = [[{'parts': [('1', 1)], 'total': 2, 'tip': [month, (1, 'in ' + period)]}] for month in ('Jan', 'Feb')]
            return share_panels([{'label': 'Operations', 'title': 'Operations by month, ' + period}],
                                [{'label': 'Months', 'periods': [{'short': 'Jan'}, {'short': 'Feb'}],
                                  'series': [{'key': [('1', 'Counted')], 'label': '', 'cells': cells}]}], name=name)
        options = [(period, chart(period)) for period in ('All years', '2026', '2025')]
        drawn = with_menu(options, label='Year')
        self.assertEqual([(o['label'], o['selected']) for o in drawn['menu']['options']],
                         [('All years', True), ('2026', False), ('2025', False)])
        self.assertEqual(drawn['titles'][0]['text'], 'Operations by month, All years')
        html = render_to_string('charts/share_panels.html', {'chart': drawn})
        self.assertInHTML('<option value="0" selected>All years</option>', html)
        # The title is told to a screen reader when the menu changes it.
        self.assertIn('data-chart-part="title" aria-live="polite"', html)
        self.assertInHTML('<option value="2">2025</option>', html)
        # The option shown, then every option again for the script to put in its place.
        self.assertEqual(html.count('data-chart-part="title"'), 4)
        self.assertEqual(html.count('data-chart-part="views"'), 4)
        self.assertEqual(html.count('<template data-chart-option='), 3)
        # Each title once to show, and once, unseen, in the title that is showing, to hold its height.
        self.assertEqual(html.count('>Operations by month, 2025<'), 1 + 1)
        self.assertEqual(html.count('data-chart-keep'), 3)
        self.assertEqual(drawn['menu']['title_sizes'], ['Operations by month, ' + p for p in ('All years', '2026', '2025')])
        # A chart without a menu has neither the control nor the copies.
        plain = render_to_string('charts/share_panels.html', {'chart': chart('2026')})
        self.assertNotIn('<select', plain)
        self.assertNotIn('<template', plain)
        with self.assertRaises(ValueError):
            with_menu([], 'Year')
        with self.assertRaises(ValueError):
            with_menu(options + [('2024', chart('2024', name='other'))], 'Year')

    def test_hours_are_written_to_one_decimal(self):
        self.assertEqual([charts.hours_text(h) for h in (0.5, 2, 1234.56)], ['0.5', '2.0', '1,234.6'])
        # Half up as written, whatever floating point makes of a sum: 3.78 and 23.77 are 27.549999...
        self.assertEqual(charts.hours_text(3.78 + 23.77), '27.6')

    def test_a_chart_has_a_name_of_its_own(self):
        view = self.view([[(1, 2)]])
        with self.assertRaises(TypeError):
            charts.share_panels(self.MEASURES, [view])
        # The name becomes an id and the radio groups' name, so it is kept to what both take.
        for name in ('', 'two words', 'a"b', '1st', '\u00e9lan'):
            with self.assertRaises(ValueError, msg=name):
                charts.share_panels(self.MEASURES, [view], name=name)
        self.assertEqual(charts.share_panels(self.MEASURES, [view], name='reply_hours-2')['name'], 'reply_hours-2')

    def test_the_gutter_fits_the_longest_tick(self):
        self.assertEqual(share_panels(self.MEASURES, [self.view([[(1, 80)]])])['digits'], 2)
        chart = share_panels(self.MEASURES, [self.view([[(1, 11500)]])])
        self.assertEqual(chart['digits'], 5)
        self.assertIn('style="--chart-digits: 5"', render_to_string('charts/share_panels.html', {'chart': chart}))

    def test_input_that_would_draw_wrongly_is_refused(self):
        def cell(parts, total=10, **more):
            return dict({'parts': parts, 'total': total, 'tip': ''}, **more)

        def chart(cells, measures=None, key=(('1', 'Counted'),), **view):
            view = dict({'label': 'Years', 'periods': [{'short': 'a'}] * len(cells),
                         'series': [{'label': 'Operations', 'key': list(key), 'cells': cells}]}, **view)
            return lambda **options: share_panels(measures or self.MEASURES, [view], **options)
        two = [{'label': 'Days', 'title': 'Days'}, {'label': 'Hours', 'title': 'Hours'}]
        wrong = {
            'is not a colour': chart([[cell([('purple', 1)])]]),
            "'ramp-9-5' is not a colour": chart([[cell([('ramp-9-5', 1)])]]),
            "'ramp-1-1' is not a colour": chart([[cell([('ramp-1-1', 1)])]]),
            'used twice': chart([[cell([('1', 3), ('1', 2)])]]),
            'different colours': chart([[cell([('1', 1), ('2', 1)]), cell([('2', 1), ('1', 1)])]], measures=two),
            'more than the total': chart([[cell([('1', 30)])]]),
            'a total is not below zero': chart([[cell([('1', 0)], total=-5)]]),
            '1 columns for 3 periods': chart([[cell([('1', 1)])]], periods=[{'short': 'a'}] * 3),
            'one entry for each measure': chart([[cell([('1', 1)])]], measures=two),
            'parts, a total and a tip': chart([[{'parts': [('1', 1)], 'total': 2}]]),
            'max_labels is at least 1': chart([[cell([('1', 1)])]], max_labels=0),
            'one for each measure': chart([[cell([('1', 1)])]], titles=['One', 'Two']),
            'every period has a short label': chart([[cell([('1', 1)])]], periods=[{'label': '2024'}]),
            'a list of them, one for each measure': chart([[cell([('1', 1)])]], titles='T'),
            'every figure is a number': chart([[cell([('1', float('nan'))])]]),
            'a tip is a line': chart([[dict(cell([('1', 1)]), tip=12)]]),
            "names them in its key, as 'marker'": chart([[cell([('1', 1)], marker=1)]]),
            # Markers and parts below zero are drawn for one measure, the only one the stylesheet places them for.
            'markers and parts below zero are for a chart of one measure': chart(
                [[cell([('1', 1)], marker=1), cell([('1', 1)])]], measures=two, key=[('1', 'Up'), ('marker', 'Net')]),
            'parts below zero are for a chart of one measure': chart(
                [[cell([('1', 1), ('2', 0)]), cell([('1', 1), ('2', -1)])]], measures=two, key=[('1', 'Up'), ('2', 'Down')]),
        }
        for message, draw in wrong.items():
            # Each says which chart, view, panel and column.
            with self.assertRaisesRegex(ValueError, "chart 'chart'.*" + message, msg=message):
                draw()
        with self.assertRaisesRegex(ValueError, "view 'Years', panel 'Operations', column 1"):
            wrong['used twice']()
        # A part below zero and a marker above the total are not mistakes.
        chart([[cell([('1', 4), ('2', -30)], marker=40)]], key=[('1', 'Up'), ('2', 'Down'), ('marker', 'Net')])()

    def test_a_menus_charts_have_the_same_measures_and_views(self):
        def chart(views):
            cells = [[{'parts': [('1', 1)], 'total': 2, 'tip': ''}]]
            return share_panels(self.MEASURES, [{'label': label, 'periods': [{'short': 'a'}],
                                                 'series': [{'label': '', 'key': [('1', 'Counted')], 'cells': cells}]}
                                                for label in views], name='ops')
        with self.assertRaisesRegex(ValueError, 'same measures and views'):
            with_menu([('All years', chart(['Months', 'Hours'])), ('2026', chart(['Months']))], 'Year')
        # The switches are drawn once, for the first option: every option has the same measures and switches.
        renamed = dict(chart(['Months']), measures=[dict(self.MEASURES[0], label='Hours', number=1)])
        with self.assertRaisesRegex(ValueError, 'same measures and views'):
            with_menu([('All years', chart(['Months'])), ('2026', renamed)], 'Year')
        switched = dict(chart(['Months']), scale_switch=True)
        with self.assertRaisesRegex(ValueError, 'same measures and views'):
            with_menu([('All years', chart(['Months'])), ('2026', switched)], 'Year')

    def test_the_keys_to_the_totals_share_one_place(self):
        # So that the note keeps its lines when the measure changes, even to one without a total.
        measures = [{'label': 'Days', 'title': 'Days', 'total_label': 'Unit active days'},
                    {'label': 'Events', 'title': 'Events', 'total_label': 'Unit events'},
                    {'label': 'Hours', 'title': 'Hours'}]
        cell = [{'parts': [('1', 1)], 'total': 2, 'tip': 't'}] * 3
        view = {'label': 'Years', 'periods': [{'short': 'a'}],
                'series': [{'label': 'S', 'key': [('1', 'A')], 'cells': [cell]}]}
        html = render_to_string('charts/share_panels.html', {'chart': share_panels(measures, [view], note='Why?')})
        self.assertIn('<span class="chart-note-keys"><span class="chart-key chart-key-m1"><i class="chart-part-total">'
                      '</i>Unit active days</span><span class="chart-key chart-key-m2">', html)
        self.assertNotIn('chart-key-m3', html)
        without = share_panels([{'label': 'Hours', 'title': 'Hours'}], [{**view, 'series': [
            {'label': 'S', 'key': [('1', 'A')], 'cells': [cell[:1]]}]}])
        self.assertNotIn('chart-note-keys', render_to_string('charts/share_panels.html', {'chart': without}))

    def test_a_switch_turns_the_totals_off(self):
        # Days against the unit's, and hours, which have no total. Off, each day column is drawn against what its
        # parts reach, on axes of its own, with its own title and figures; hours are drawn as they were.
        measures = [{'label': 'Days', 'title': 'Days / unit days', 'title_without_total': 'Days',
                     'total_label': 'Unit days'},
                    {'label': 'Hours', 'title': 'Hours'}]

        def cell(days, unit, hours):
            return [{'parts': [('1', days[0]), ('2', days[1])], 'total': unit,
                     'tip': ['2024', ('{} of {}'.format(sum(days), unit), 'days'), 'a line'],
                     'tip_without_total': ['2024', (sum(days), 'days'), 'a line']},
                    {'parts': [('1', hours[0]), ('2', hours[1])], 'total': sum(hours), 'tip': ['2024', (sum(hours), 'hours')]}]
        view = {'label': 'Years', 'periods': [{'short': 'a'}, {'short': 'b'}],
                'series': [{'label': 'S', 'key': [('1', 'A'), ('2', 'B')], 'cells': [cell((5, 5), 20, (3, 1)),
                                                                                     cell((2, 0), 10, (1, 1))]}]}
        chart = share_panels(measures, [view], note='How many, against the unit?', note_without_total='How many?',
                             total_switch_label='Unit figures')
        self.assertEqual((chart['total_switch_label'], chart['size_suffix']), ('Unit figures', '-whole'))
        panel = chart['views'][0]['panels'][0]
        first, second = panel['cells']
        # Against the unit's 20, and against the 10 the parts reach, on an axis to 10.
        self.assertEqual((first['own'], first['own_by_parts'], second['own_by_parts']), ([100, 100], [(1, 100)], [(1, 20)]))
        self.assertEqual(first['parts'], [{'colour': '1', 'sizes': [25, 75], 'sizes_by_parts': [(1, 50)]},
                                          {'colour': '2', 'sizes': [25, 25], 'sizes_by_parts': [(1, 50)]}])
        self.assertEqual([(t['measure'], t['scale'], t.get('only'), [tick['value'] for tick in t['ticks']])
                          for t in panel['ticks']],
                         [(1, 'own', 'total', [20, 10, 0]), (1, 'shared', 'total', [20, 10, 0]),
                          (2, 'own', None, [4, 2, 0]), (2, 'shared', None, [4, 2, 0]),
                          (1, 'own', 'no-total', [10, 5, 0]), (1, 'shared', 'no-total', [10, 5, 0])])
        # The line that reads otherwise carries how it reads then; the rest are as they were.
        self.assertEqual(first['tips'][0]['lines'], [{'number': '10 of 20', 'label': 'days',
                                                      'without': {'number': 10, 'label': 'days'}}, {'text': 'a line'}])
        self.assertEqual(first['tips'][1]['lines'], [{'number': 4, 'label': 'hours'}])
        self.assertEqual(chart['titles'], [{'measure': 1, 'view': 1, 'text': 'Days / unit days', 'without': 'Days'},
                                           {'measure': 2, 'view': 1, 'text': 'Hours'}])
        html = render_to_string('charts/share_panels.html', {'chart': chart})
        # The switch, On to start with, as a browser without the switches shows the chart.
        self.assertIn('<span class="chart-control-label" id="chart-total-label">Unit figures</span>', html)
        self.assertIn('<div class="chart-switch" role="radiogroup" aria-labelledby="chart-total-label">', html)
        self.assertIn('<input type="radio" name="chart-total" checked><span>On</span>', html)
        self.assertIn('<input type="radio" name="chart-total" class="chart-pick-no-total"><span>Off</span>', html)
        # Both sizes of each column and part, measured against the total and against the parts.
        self.assertIn('style="--m1-own-whole: 100.0%; --m2-own-whole: 100.0%; --m1-shared-whole: 100.0%; '
                      '--m2-shared-whole: 100.0%; --m1-own-parts: 100.0%; --m1-shared-parts: 100.0%; "', html)
        self.assertIn('style="--m1-whole: 25.0%; --m2-whole: 75.0%; --m1-parts: 50.0%; "', html)
        self.assertIn('class="chart-tick chart-m1 chart-own chart-only-no-total"', html)
        self.assertIn('<div class="chart-m1 chart-v1 chart-pair"><span class="chart-only-total">Days / unit days'
                      '</span><span class="chart-only-no-total">Days</span></div>', html)
        self.assertIn('<div class="chart-tip-pair chart-only-total"><div class="chart-tip-number">10 of 20</div>'
                      '<div>days</div></div><div class="chart-tip-pair chart-only-no-total"><div class="chart-tip-number">'
                      '10</div><div>days</div></div><div class="chart-tip-text">a line</div>', html)
        self.assertIn('<span class="chart-note-keys"><span class="chart-key chart-key-m1">', html)
        self.assertIn('<span class="chart-pair"><span class="chart-only-total">How many, against the unit?</span>'
                      '<span class="chart-only-no-total">How many?</span></span>', html)
        # A chart without the switch is drawn as before.
        unswitched = dict(view, series=[dict(view['series'][0], cells=[
            [{key: value for key, value in entry.items() if key != 'tip_without_total'} for entry in cell]
            for cell in view['series'][0]['cells']])])
        plain = render_to_string('charts/share_panels.html', {'chart': share_panels(measures, [unswitched])})
        for name in ('-whole', '-parts', 'chart-only-total', 'chart-only-no-total', 'chart-pick-no-total', '-pair'):
            self.assertNotIn(name, plain, name)
        self.assertIn('style="--m1-own: 100.0%; --m2-own: 100.0%; --m1-shared: 100.0%; --m2-shared: 100.0%; "', plain)

    def test_a_switch_for_the_totals_is_refused_where_it_would_draw_wrongly(self):
        def chart(measures=None, entry=None, **view):
            days = dict({'parts': [('1', 1)], 'total': 2, 'tip': ['2024', ('1 of 2', 'days')]}, **(entry or {}))
            view = dict({'label': 'Years', 'periods': [{'short': 'a'}],
                         'series': [{'label': 'S', 'key': [('1', 'A')], 'cells': [[days]]}]}, **view)
            measures = measures or [{'label': 'Days', 'title': 'Days', 'total_label': 'Unit', 'title_without_total': 'D'}]
            return lambda **options: share_panels(measures, [view], **dict({'total_switch_label': 'Unit figures'}, **options))
        wrong = {
            'for a chart with a measure that has one': chart([{'label': 'Days', 'title': 'Days'}]),
            'a measure with a total has a title_without_total': chart([{'label': 'Days', 'title': 'Days', 'total_label': 'Unit'}]),
            'a view has none': chart(titles=['Days by year']),
            'the heading of the tip, and as many lines': chart(entry={'tip_without_total': ['2025', (1, 'day')]}),
            'and as many lines': chart(entry={'tip_without_total': ['2024']}),
            'for a chart without a switch for the totals': chart(entry={'parts': [('1', 1), ('2', -1)]}),
        }
        for message, draw in wrong.items():
            with self.assertRaisesRegex(ValueError, "chart 'chart'.*" + message, msg=message):
                draw()
        with self.assertRaisesRegex(ValueError, 'tip_without_total is for a measure with a total, on a chart with a switch'):
            chart(entry={'tip_without_total': ['2024', (1, 'day')]})(total_switch_label='')
        for options in ({'note': 'Why?', 'note_without_total': 'Why?', 'total_switch_label': ''}, {'note_without_total': 'Why?'}):
            with self.assertRaisesRegex(ValueError, 'note_without_total is for a chart with a note and a switch', msg=options):
                chart()(**options)
        # A menu's charts all have the switch, or none does: one set of switches serves them all.
        draw = chart()
        with self.assertRaisesRegex(ValueError, 'same measures and views'):
            with_menu([('All years', draw()), ('2026', draw(total_switch_label=''))], 'Year')

    def test_a_panel_of_a_column_or_two_has_room_for_its_key_and_figures(self):
        # A first-year member's panels have one column each. They are drawn as wide as a panel is readable, so
        # the keys wrap alike in every view (the chart keeps its height) and two thirds of the plot hold the
        # figures; measured in Chromium and WebKit.
        css = re.sub(r'/\*.*?\*/', '', open(finders.find('css/charts.css')).read(), flags=re.S)
        panel = re.search(r'\.chart-panel \{ max-width: ([^;]*);', css)[1]
        self.assertIn('max(var(--chart-panel-min), calc(var(--chart-gutter)', ' '.join(panel.split()))
        self.assertIn('.chart-key { white-space: nowrap; }', css)
        # The figures box is a share of its plot, never a fixed width, which would overhang a narrow tile.
        tip = re.search(r'\.chart-band:hover \.chart-tip, \.chart-band:focus \.chart-tip \{([^}]*)\}', css)[1]
        self.assertIn('max-width: 66%;', tip)
        # Its padding and border inside that two thirds, not added to it.
        self.assertIn('.chart-tip { box-sizing: border-box;', css)
        self.assertNotRegex(tip, r'max-width: [^;]*(rem|px)')
        # But it grows past that for a number and a word, which cannot wrap ("16 Operations" on a narrow panel):
        # labels wrap between words, never out of the box.
        self.assertIn('min-width: min-content;', tip)
        self.assertIn('.chart-tip-lines { display: grid; grid-template-columns: auto minmax(min-content, 1fr);', css)
        self.assertIn('.chart-tip-number { text-align: right; white-space: nowrap; }', css)

    def test_the_ramp_falls_back_to_the_series_colour_without_color_mix(self):
        # A declaration using var() is accepted when read and fails only when computed, leaving no colour;
        # so color-mix() is used only inside @supports, after a plain fallback.
        css = re.sub(r'/\*.*?\*/', '', open(finders.find('css/charts.css')).read(), flags=re.S)
        self.assertIn('.chart-part-ramp { background: var(--chart-series-1); }', css)
        outside = re.sub(r'@supports \(color: color-mix\(in oklab, red, red\)\) \{.*?\n\}', '', css, flags=re.S)
        self.assertIn('color-mix(', css)
        self.assertNotIn('color-mix(', outside)

    def test_everything_the_page_names_is_in_the_stylesheet(self):
        """The Python, the templates and charts.css agree only by the names they
        share. Draw a chart that uses everything and check that each class and
        each custom property in the page has a rule or a use in charts.css."""
        colours = sorted(charts.COLOURS) + ['ramp-2-5']

        def view(label, measures):
            # Markers and parts below zero are for a chart of one measure.
            one = len(measures) == 1
            switched = all('title_without_total' in measure for measure in measures)
            cells = [[dict({'parts': [(colour, 1) for colour in colours], 'total': 20,
                            'tip': ['Head', (1, 'counted'), 'a line']}, **({'marker': 3} if one else {}),
                           **({'tip_without_total': ['Head', (1, 'counted alone'), 'a line']} if switched else {}))
                      for _ in measures] for _ in range(3)]
            series = [{'label': 'Every colour', 'cells': cells,
                       'key': [(colour, colour) for colour in colours] + ([('marker', 'Net')] if one else [])}]
            if one:
                series.append({'label': 'Below zero', 'key': [('1', 'Up'), ('2', 'Down'), ('marker', 'Net')],
                               'cells': [[{'parts': [('1', 4), ('2', -3)], 'total': 5, 'tip': 'x', 'marker': 1}]
                                         for _ in range(3)]})
            return {'label': label, 'periods': [{'short': 'a'}, {'short': ''}, {'short': 'c'}],
                    'titles': ['{} {}'.format(label, m) for m in range(1, len(measures) + 1)], 'series': series}
        four = [{'label': 'M{}'.format(m), 'title': 'Measure {}'.format(m), 'total_label': 'Whole'} for m in range(1, 5)]
        chart = with_menu([(option, share_panels(four, [view(v, four) for v in 'ABC'], note='A note', name='everything'))
                           for option in ('All years', '2026')], label='Year')
        net = [{'label': 'Net', 'title': 'Net', 'total_label': 'Whole'}]
        signed = share_panels(net, [view(v, net) for v in 'AB'], note='A note', name='signed')
        # And a chart with a switch for its totals, whose measures' titles are its titles.
        totals = [dict(measure, title_without_total=measure['title'] + ' alone') for measure in four]
        switched = share_panels(totals, [{key: value for key, value in view(v, totals).items() if key != 'titles'}
                                         for v in 'AB'], name='switched', total_switch_label='Totals')
        html = ''.join(render_to_string('charts/share_panels.html', {'chart': c}) for c in (chart, signed, switched))
        css = open(finders.find('css/charts.css')).read()
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        classes = {name for names in re.findall(r'class="([^"]*)"', html) for name in names.split() if name.startswith('chart')}
        properties = set(re.findall(r'(--[\w-]+)\s*:', html))
        self.assertGreater(len(classes), 25)
        self.assertGreater(len(properties), 15)
        # A class needs a rule. Three only mark a place: for the page's own
        # style (the head), for the tiles' rows (main), and the view shown first.
        marks = {'chart-head', 'chart-main', 'chart-v1'}
        self.assertEqual(sorted(name for name in classes - marks
                                if not re.search(r'\.' + re.escape(name) + r'(?![\w-])', css)), [])
        self.assertEqual(sorted(name for name in properties
                                if not re.search(r'var\(' + re.escape(name) + r'(?![\w-])', css)), [])
        # And every measure's property the stylesheet reads is one a chart sets: no rule for what none draws.
        self.assertEqual(sorted(set(re.findall(r'var\((--m\d-[\w-]+)', css)) - properties), [])
        # And the other way: every class the stylesheet styles is one the page has, but for those a
        # page or the script puts there, and those only the page's states give (the measure and view picked).
        styled = set(re.findall(r'\.(chart-[\w-]+)', css))
        put_by_page = {'chart-tiles', 'chart-grid', 'chart-page', 'chart-scripted'}
        self.assertEqual(sorted(name for name in styled - classes - put_by_page
                                if not re.fullmatch(r'chart-(part-[\w-]+|tip-(left|right|centre)|pick-[\w-]+|v\d|m\d)', name)), [])
        for name in ('chart-signed', 'chart-x-axis', 'chart-baseline', 'chart-down', 'chart-under', 'chart-marker',
                     'chart-only-total', 'chart-only-no-total', 'chart-pair', 'chart-tip-pair'):
            self.assertIn(name, classes, name)
        # Read by a screen reader: each column's figures, named by their panel; not the axes.
        self.assertIn('<div class="chart-bands chart-x-axis" aria-hidden="true">', html)
        self.assertIn('<div><b>Every colour Head</b></div>', html)
        # Printed, the columns keep their colours.
        self.assertIn('.chart, .chart * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }', css)
        # And the script's hooks are in the page: every class and every data- attribute it reads, wherever
        # in the script it names them; and the class it sets on the page has rules to act on.
        script = open(finders.find('js/charts.js')).read()
        for name in set(re.findall(r'\.(chart-[\w-]+)', script)):
            self.assertIn(name, classes, name)
        attributes = set(re.findall(r'data-chart-[\w-]+', html))
        self.assertEqual(set(re.findall(r'data-chart-[\w-]+', script)), attributes)
        self.assertIn('template[data-chart-option="', script)
        self.assertIn("classList.add('chart-scripted')", script)
        self.assertRegex(css, r'\.chart-scripted \.chart-control\.chart-menu \{ display: inline-flex; \}')
        # Without :has() the switches are hidden; in forced colours the columns keep their colours.
        self.assertRegex(css, r'@supports not selector\(:has\(\*\)\) \{\s*\.chart-control:not\(\.chart-menu\) \{ display: none; \}')
        self.assertRegex(css, r'@media \(forced-colors: active\) \{\s*\.chart-column, \.chart-column div, '
                              r'\.chart-key i, \.chart-marker \{ forced-color-adjust: none; \}')

    def test_a_tapped_column_s_figures_are_put_away_by_a_tap_on_it_or_elsewhere(self):
        # What js/charts.js relies on: each column of a plot takes focus but is no Tab stop, and holds its figures.
        view = self.view([[(2, 4), (3, 4), (4, 4)]])
        html = render_to_string('charts/share_panels.html', {'chart': share_panels(self.MEASURES, [view])})
        bands = html.split('<div class="chart-band" role="listitem" tabindex="-1">')[1:]
        self.assertEqual(len(bands), 3)
        self.assertTrue(all('<div class="chart-tip chart-tip-' in band for band in bands))
        # The script: a tap, not a drag, on another column shows its figures; on the column showing them, or
        # anywhere but the box, puts them away, decided from what showed as it came down. A pointer coming down on
        # a column does not focus it itself, and for a second, or until the next pointer or key, what the tap
        # chose is kept against the mouse events and the click a touch may send after it, as iOS does.
        script = open(finders.find('js/charts.js')).read()
        for hook in ("addEventListener('pointerdown'", "addEventListener('pointerup'", "closest('.chart-plot .chart-band')",
                     "closest('.chart-tip')", 'event.preventDefault()', 'Math.abs(event.clientX - at.x) > 10',
                     "addEventListener('mousedown'", "addEventListener('focusin'", "addEventListener('click'",
                     'Date.now() + 1000', 'kept.shows.focus({preventScroll: true})', 'shown.blur()'):
            self.assertIn(hook, script)
        keys = script.index("addEventListener('keydown'")
        self.assertIn('kept = null;', script[keys:script.index('\n', script.index('{', keys) + 1) + 80])
        # On a touch screen a column keeps :hover after a tap, so only focus shows figures there, and the box
        # takes taps while it shows; with a mouse the box lets the pointer through, as before.
        css = re.sub(r'/\*.*?\*/', '', open(finders.find('css/charts.css')).read(), flags=re.S)
        touch = re.search(r'@media \(hover: none\) \{(.*?)\n\}', css, flags=re.S)[1]
        hidden = re.search(r'\.chart-band:hover:not\(:focus\) \.chart-tip \{([^}]*)\}', touch)[1]
        self.assertIn('clip-path: inset(50%);', hidden)
        self.assertIn('.chart-band:focus .chart-tip { pointer-events: auto; }', touch)
        self.assertIn('pointer-events: none;', re.search(r'\.chart-tip \{([^}]*)\}', css)[1])

    def test_narrow_columns_touch_and_keep_the_total_pale(self):
        # A column takes its band less a gap that shrinks to nothing as bands narrow, from 2px at 10px down to
        # none at 6px, so that many columns (a member's months over years) touch, with a pixel at least, so none
        # vanishes. The total is the pale fill; its edge, on the top and the sides alike, is a pixel on a column
        # that keeps its full gap (8px wide, in a band of 10px or more) and nothing on a narrower one, read from
        # the column's own width: no fractional edge at any width, and no top line without its sides.
        css = re.sub(r'/\*.*?\*/', '', open(finders.find('css/charts.css')).read(), flags=re.S)
        column = ' '.join(re.search(r'\n\.chart-column \{([^}]*)\}', css)[1].split())
        self.assertIn('width: calc(100% - clamp(0px, calc((100% - 6px) / 2), 2px));', column)
        self.assertIn('min-width: 1px;', column)
        # A column of nothing, drawn for another measure or with the totals off, shows nothing, its edge neither.
        self.assertIn('min-height: min(1px, calc(var(--chart-size) * 100));', column)
        self.assertIn('overflow: hidden;', column)
        self.assertNotIn('box-shadow', column)
        self.assertIn('background: var(--chart-total);', column)
        self.assertIn('container-type: inline-size;', column)
        self.assertIn('isolation: isolate;', column)
        edge = ' '.join(re.search(r'\n\.chart-column::before \{([^}]*)\}', css)[1].split())
        self.assertIn('--chart-edge: clamp(0px, calc((100cqw - 7.99px) * 100), 1px);', edge)
        self.assertIn('border: 1px solid var(--chart-total-edge); border-width: var(--chart-edge) var(--chart-edge) 0;', edge)
        self.assertIn('z-index: -1;', edge)
        # The key's swatch keeps its full edge.
        self.assertIn('.chart-note .chart-key i.chart-part-total { box-shadow: inset 0 0 0 1px var(--chart-total-edge); }', css)

    def test_every_panel_has_a_key(self):
        # Even one colour is named: what the columns count.
        view = self.view([[(1, 2)]], key=[('1', 'Pages')])
        self.assertEqual(share_panels(self.MEASURES, [view])['views'][0]['panels'][0]['key'],
                         [{'colour': '1', 'label': 'Pages'}])
        with self.assertRaises(ValueError):
            share_panels(self.MEASURES, [self.view([[(1, 2)]], key=())])

    def test_parts_below_zero_a_marker_and_the_ramp(self):
        # Joined and left, with the net marked: 6 up and 2 down, then 0 up and 4 down.
        cells = [[{'parts': [('1', 6), ('muted', -2)], 'total': 6, 'tip': '', 'marker': 4}],
                 [{'parts': [('1', 0), ('muted', -4)], 'total': 0, 'tip': '', 'marker': -4}]]
        periods = [{'short': '1'}, {'short': '2'}]
        view = {'label': 'Years', 'periods': periods,
                'series': [{'label': '', 'key': [('marker', 'Net'), ('ramp-3-5', 'Third')], 'cells': cells}]}
        chart = share_panels(self.MEASURES, [view])
        panel = chart['views'][0]['panels'][0]
        # The axis runs from 6 to -6 in even steps, with zero half way up.
        self.assertEqual([(t['value'], t['at']) for t in panel['ticks'][0]['ticks']],
                         [(6, 100), (3, 75), (0, 50), (-3, 25), (-6, 0)])
        self.assertTrue(panel['ticks'][0]['ticks'][2]['base'])
        self.assertEqual(panel['signed'], {'own': 0.5, 'shared': 0.5})
        first, second = panel['cells']
        self.assertEqual((first['own'], first['parts']), ([100], [{'colour': '1', 'sizes': [100]}]))
        self.assertEqual(first['under'], {'own': [33.33], 'shared': [33.33],
                                          'parts': [{'colour': 'muted', 'sizes': [100]}]})
        self.assertEqual(first['marker'], {'own': 83.33, 'shared': 83.33})
        self.assertEqual((second['drawn'], second['under']['own'], second['marker']['own']),
                         (False, [66.67], 16.67))
        # Uneven: 4 up and 12 down. Steps of 6 run from 6 to -12, so a third of the plot is above zero.
        uneven = share_panels(self.MEASURES, [dict(view, periods=periods[:1], series=[{
            'label': '', 'key': [('1', 'Up'), ('muted', 'Down')],
            'cells': [[{'parts': [('1', 4), ('muted', -12)], 'total': 4, 'tip': ''}]]}])])['views'][0]['panels'][0]
        self.assertEqual([t['value'] for t in uneven['ticks'][0]['ticks']], [6, 0, -6, -12])
        self.assertEqual(uneven['signed']['own'], 0.3333)
        self.assertEqual((uneven['cells'][0]['own'], uneven['cells'][0]['under']['own']), ([66.67], [100]))
        # A step of the ramp is placed along it; the marker is named in the key.
        self.assertEqual(panel['key'], [{'colour': 'marker', 'label': 'Net'},
                                        {'colour': 'ramp', 'ramp': 50, 'label': 'Third'}])
        # With every part at zero or above, the panel is drawn as before.
        plain = share_panels(self.MEASURES, [dict(view, series=[{'key': [('1', 'Counted')], 'label': '', 'cells': [
            [{'parts': [('ramp-1-5', 3)], 'total': 6, 'tip': ''}]]}], periods=periods[:1])])
        panel = plain['views'][0]['panels'][0]
        self.assertFalse(panel['signed'])
        self.assertEqual(panel['cells'][0]['parts'], [{'colour': 'ramp', 'ramp': 0, 'sizes': [50]}])
        self.assertNotIn('under', panel['cells'][0])

    def test_the_scale_switch_starts_on_the_shared_scale(self):
        # Shared is the scale as drawn, so a browser without the switches shows it too, and it comes first.
        cells = [[{'parts': [('1', 1)], 'total': 1, 'tip': ''}]]
        view = {'label': 'V', 'periods': [{'short': '1'}],
                'series': [{'key': [('1', 'Counted')], 'label': label, 'cells': cells} for label in ('S', 'T')]}
        html = render_to_string('charts/share_panels.html', {'chart': share_panels(self.MEASURES, [view])})
        self.assertLess(html.index('<input type="radio" name="chart-scale" checked><span>Shared</span>'),
                        html.index('<input type="radio" name="chart-scale" class="chart-pick-own"><span>Separate</span>'))
        # Its words say which scale it sets, and name it for a screen reader.
        self.assertIn('<span class="chart-control-label" id="chart-scale-label">Y-axis scale</span>', html)
        self.assertIn('<div class="chart-switch" role="radiogroup" aria-labelledby="chart-scale-label">', html)
        self.assertNotIn('>Scale<', html)

    def test_a_column_far_below_the_largest_is_drawn_as_a_hairline(self):
        # One of 100,000 is 0.001% of the shared axis, which two places would make nothing.
        chart = share_panels(self.MEASURES, [self.view([[(1, 1)], [(100000, 100000)]])])
        small = chart['views'][0]['panels'][0]['cells'][0]
        self.assertEqual((small['shared'], small['own']), ([0.01], [50]))

    def test_one_scale(self):
        # With one scale, a small series is drawn against the largest total.
        chart = share_panels(self.MEASURES, [self.view([[(5, 10)], [(50, 100)]])])
        small = chart['views'][0]['panels'][0]
        self.assertEqual((small['cells'][0]['own'], small['cells'][0]['shared']), ([100], [10]))
        self.assertEqual([t['value'] for t in small['ticks'][1]['ticks']], [100, 50, 0])

    def test_time_axis(self):
        # Twenty periods are too many to label each; the last is always labelled.
        chart = share_panels(self.MEASURES, [self.view([[(0, 0)] * 20])])
        shown = [p['label'] for p in chart['views'][0]['axis'] if p['shown']]
        self.assertEqual(shown, ['1', '4', '7', '10', '13', '16', '19'])
        # Periods without a short label stay unlabelled.
        periods = [{'short': 'x' if n % 12 == 0 else ''} for n in range(30)]
        view = share_panels(self.MEASURES, [self.view([[(0, 0)] * 30], periods)])['views'][0]
        self.assertEqual([i for i, p in enumerate(view['axis']) if p['shown']], [0, 12, 24])


class BreakpointsTestCase(SimpleTestCase):
    """A media or container query cannot read a custom property, so each
    breakpoint is a number worked out from the sizes in charts.css by the
    formulas in its "Breakpoints" note. Work each out again."""

    def queries(self, text):
        """{('media' or 'container', 'min' or 'max', rem)} for every width the text's queries test."""
        preludes = re.findall(r'@(media|container)([^{]*)\{', text)
        found = [(kind, edge, float(value)) for kind, prelude in preludes
                 for edge, value in re.findall(r'\((min|max)-width:\s*([\d.]+)rem\)', prelude)]
        # Every width is in rem, so that none is missed here.
        self.assertEqual(sum(prelude.count('-width') for _, prelude in preludes), len(found))
        return set(found)

    def test_every_breakpoint_follows_from_the_sizes(self):
        css = open(finders.find('css/charts.css')).read()
        tokens = css[css.index('.chart, .chart-tiles'):]
        tokens = tokens[:tokens.index('}')]
        size = {name: float(value) for name, value in re.findall(r'--chart-([\w-]+):\s*([\d.]+)rem;', tokens)}

        def fit(n, each, gap, margin=0.0):
            return n * each + (n - 1) * gap + 2 * margin

        def short_of(width):
            return round(width - 0.01, 2)
        tiles = {n: fit(n, size['tile-min'], size['tile-gap'], size['page-margin']) for n in (2, 4)}
        panels = {n: fit(n, size['panel-min'], size['panel-gap']) for n in (2, 3, 4, 5)}
        phone = short_of(tiles[2])
        # The rules lay panels and tiles out by the same tokens the breakpoints are worked out from.
        self.assertIn('grid-template-columns: repeat(auto-fit, minmax(min(var(--chart-panel-min), 100%), 1fr))', css)
        self.assertIn('.chart-panels { display: grid; gap: 0.6rem var(--chart-panel-gap);', css)
        self.assertIn('.chart-tiles { display: grid; gap: 1rem var(--chart-tile-gap); '
                      'grid-template-columns: minmax(0, var(--chart-tile)); }', css)
        for n in (2, 4):      # tiles share the line up to their widest, from no width: the breakpoints say when n fit
            self.assertIn('.chart-tiles { grid-template-columns: repeat(' + str(n) + ', minmax(0, var(--chart-tile))); }', css)
        self.assertIn('padding-left: var(--chart-page-margin); padding-right: var(--chart-page-margin);', css)
        self.assertEqual(self.queries(css), {
            ('media', 'max', phone), ('media', 'min', tiles[2]), ('media', 'min', tiles[4]),
            ('container', 'min', panels[2]), ('container', 'max', short_of(panels[3])),
            ('container', 'min', panels[4]), ('container', 'max', short_of(panels[5])),
            ('container', 'min', panels[5])})

        def page(name):
            return open(get_template(name).origin.name).read()
        # The member report's tables change at widths of their own: the events lists a little above a phone, and the
        # summary where a member with every duty no longer fits (activity-member.html says so).
        self.assertEqual(self.queries(page('reports/activity-member.html')),
                         {('media', 'max', 34.0), ('media', 'max', 47.0)})
        self.assertGreater(34.0, phone)
        self.assertEqual(self.queries(page('reports/activity-unit.html')), set())
        # The glossary's column of terms is 16% wide, or 7rem where 16% is less.
        style = page('reports/activity_charts_style.html')
        share = float(re.search(r'col\.glossary-term \{ width: ([\d.]+)%; \}', style)[1])
        least = float(re.search(r'col\.glossary-term \{ width: ([\d.]+)rem; \}', style)[1])
        self.assertEqual(self.queries(style), {('media', 'max', round(least / (share / 100), 2))})


class SwitchesTestCase(SimpleTestCase):
    """What each setting of a chart's switches shows, worked out from the
    :has() rules in charts.css as a browser would apply them: the rules that
    match an element, the most specific last. Every measure, view and scale."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        css = re.sub(r'/\*.*?\*/', '', open(finders.find('css/charts.css')).read(), flags=re.S)
        top = re.sub(r'@[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}', '', css)        # @media and @supports blocks are not these
        cls.rules = [(selector.strip(), body) for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', top)
                     for selector in selectors.split(',')]

    @staticmethod
    def compounds(selector):
        """A selector's compounds, from the outermost: [(tag, {classes}, {pick: checked or not})]."""
        out = []
        for part in re.findall(r'(?:[^\s(]|\([^)]*\)\)?)+', selector):
            picks = {name: True for name in re.findall(r'(?<!:not\():has\(\.chart-pick-([\w-]+):checked\)', part)}
            picks.update({name: False for name in re.findall(r':not\(:has\(\.chart-pick-([\w-]+):checked\)\)', part)})
            plain = re.sub(r':(not\(:has|has)\([^)]*\)\)?', '', part)
            out.append((re.match(r'[a-z]*', plain)[0], set(re.findall(r'\.([\w-]+)', plain)), picks))
        return out

    def shown(self, path, prop, picked):
        """The value `prop` ends with on the last element of `path`, a list of (tag, {classes}) from the
        chart down, for the picks checked."""
        best = None
        for order, (selector, body) in enumerate(self.rules):
            value = re.search(r'(?:^|;)\s*' + prop + r':\s*([^;]+)', body)
            parts = self.compounds(selector)
            if not value or not parts:
                continue
            *above, last = parts

            def matches(compound, element):
                tag, classes, picks = compound
                return ((not tag or tag == element[0]) and classes <= element[1]
                        and all((name in picked) == checked for name, checked in picks.items()))
            if not matches(last, path[-1]):
                continue
            ancestors = iter(path[:-1])
            if not all(any(matches(compound, element) for element in ancestors) for compound in above):
                continue
            specificity = (sum(selector.count(c) for c in ('.', ':checked')), len(re.findall(r'(?:^|\s)div', selector)))
            if best is None or (specificity, order) >= best[0]:
                best = ((specificity, order), value[1].strip())
        return best and best[1]

    def test_every_setting_shows_one_title_one_set_of_ticks_one_view_and_its_measure(self):
        chart = ('div', {'chart'})
        for m in (1, 2, 3, 4):
            for v in (1, 2, 3, 4):
                for scale in ('own', 'shared'):
                    picked = {name for name, on in (('m2', m == 2), ('m3', m == 3), ('m4', m == 4), ('v2', v == 2),
                                                    ('v3', v == 3), ('v4', v == 4), ('own', scale == 'own')) if on}
                    state = 'measure {}, view {}, {} scale'.format(m, v, scale)
                    titles = {(tm, tv) for tm in (1, 2, 3, 4) for tv in (1, 2, 3, 4) if self.shown(
                        [chart, ('div', {'chart-title'}), ('div', {'chart-m%d' % tm, 'chart-v%d' % tv})],
                        'visibility', picked) == 'visible'}
                    self.assertEqual(titles, {(m, v)}, state)
                    ticks = {(tm, ts) for tm in (1, 2, 3, 4) for ts in ('own', 'shared') if self.shown(
                        [chart, ('div', {'chart-plot'}), ('div', {'chart-tick', 'chart-m%d' % tm, 'chart-' + ts})],
                        'display', picked) not in (None, 'none')}
                    self.assertEqual(ticks, {(m, scale)}, state)
                    views = {tv for tv in (1, 2, 3, 4) if self.shown(
                        [chart, ('div', {'chart-panels', 'chart-v%d' % tv})], 'display', picked) not in (None, 'none')}
                    self.assertEqual(views, {v}, state)
                    figures = {tm for tm in (1, 2, 3, 4) if self.shown(
                        [chart, ('div', {'chart-tip'}), ('div', {'chart-only-m%d' % tm})], 'display', picked) != 'none'}
                    self.assertEqual(figures, {m}, state)
                    keys = {tm for tm in (1, 2, 3, 4) if self.shown(
                        [chart, ('div', {'chart-panel-key'}), ('span', {'chart-key', 'chart-key-m%d' % tm})],
                        'visibility', picked) != 'hidden'}
                    self.assertEqual(keys, {m}, state)
                    self.assertIsNone(self.shown([chart, ('div', {'chart-panel-key'}), ('span', {'chart-key'})],
                                                 'visibility', picked), state)

    def test_the_switch_for_the_totals_shows_one_setting_s_sizes_ticks_titles_and_figures(self):
        chart = ('div', {'chart'})
        for m in (1, 2, 3, 4):
            for scale in ('own', 'shared'):
                for total in (True, False):
                    picked = {name for name, on in (('m2', m == 2), ('m3', m == 3), ('m4', m == 4), ('own', scale == 'own'),
                                                    ('no-total', not total)) if on}
                    state = 'measure {}, {} scale, totals {}'.format(m, scale, 'on' if total else 'off')
                    # The column's size and its parts' heights are those measured against the total, or the parts.
                    size = '--m{}-{}'.format(m, scale)
                    self.assertEqual(self.shown([chart, ('div', {'chart-column'})], size, picked),
                                     'var({}-whole)'.format(size) if total else
                                     'var({0}-parts, var({0}-whole))'.format(size), state)
                    self.assertEqual(self.shown([chart, ('div', {'chart-column'}), ('div', set())], '--m%d' % m, picked),
                                     'var(--m{}-whole)'.format(m) if total else 'var(--m{0}-parts, var(--m{0}-whole))'.format(m),
                                     state)
                    # One set of ticks: the measure's and the scale's, for the setting of the totals.
                    ticks = {(tm, ts, only) for tm in (1, 2, 3, 4) for ts in ('own', 'shared') for only in ('total', 'no-total')
                             if self.shown([chart, ('div', {'chart-plot'}),
                                            ('div', {'chart-tick', 'chart-m%d' % tm, 'chart-' + ts, 'chart-only-' + only})],
                                           'display', picked) not in (None, 'none')
                             and self.shown([chart, ('div', {'chart-plot'}),
                                             ('div', {'chart-tick', 'chart-m%d' % tm, 'chart-' + ts, 'chart-only-' + only})],
                                            'visibility', picked) != 'hidden'}
                    self.assertEqual(ticks, {(m, scale, 'total' if total else 'no-total')}, state)
                    # The title's words for the setting, and the figures' lines; the keys to the totals only with them.
                    words = {only for only in ('total', 'no-total') if self.shown(
                        [chart, ('div', {'chart-title'}), ('div', {'chart-m1', 'chart-v1', 'chart-pair'}),
                         ('span', {'chart-only-' + only})], 'visibility', picked) != 'hidden'}
                    self.assertEqual(words, {'total' if total else 'no-total'}, state)
                    lines = {only for only in ('total', 'no-total') if self.shown(
                        [chart, ('div', {'chart-tip'}), ('div', {'chart-tip-pair', 'chart-only-' + only})],
                        'display', picked) != 'none'}
                    self.assertEqual(lines, {'total' if total else 'no-total'}, state)
                    keys = self.shown([chart, ('div', {'chart-note'}), ('span', {'chart-note-keys'})], 'display', picked)
                    self.assertEqual(keys != 'none', total, state)
                    self.assertEqual(self.shown([chart, ('div', {'chart-note'}), ('span', {'chart-note-keys'}),
                                                 ('span', {'chart-key', 'chart-key-m%d' % m})], 'visibility', picked),
                                     'inherit', state)

    def test_the_script_and_the_figures_box_keep_their_contract(self):
        # Alt, Ctrl and Cmd with an arrow are the browser's; the box starts, centres or ends at its column.
        script = open(finders.find('js/charts.js')).read()
        self.assertIn('if (event.altKey || event.ctrlKey || event.metaKey) { return; }', script)
        css = open(finders.find('css/charts.css')).read()
        for rule in ('.chart-tip-left { left: var(--chart-tip-at); }', '.chart-tip-right { right: var(--chart-tip-at); }',
                     '.chart-tip-centre { left: var(--chart-tip-at); transform: translateX(-50%); }'):
            self.assertIn(rule, css)
