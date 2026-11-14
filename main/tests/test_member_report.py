"""A member's activity report: its chart and table (main.lib.activity), and the page."""
from datetime import timedelta

from django.test import Client
from django.urls import reverse

from main.lib.activity import glossary, member_activity
from main.lib.counting import activity_rows, member_entries, records_from, reported_events
from main.lib.report_settings import report_settings
from main.models import DoAvailable, Event, Participant
from main.tests.helpers import NOW, ActivityTestCase, PageTestCase, when


class MemberActivityTestCase(ActivityTestCase):
    def test_ahc_hours_are_named_in_the_key_without_an_ahc_day(self):
        # AHC in the morning and in the field that afternoon: a day in the field, with AHC hours.
        operation = self.make_event('operation', when(2024, 3, 10), attended=[self.member])
        Participant.objects.create(period=operation.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 10) - timedelta(hours=4),
                                   return_home_at=when(2024, 3, 10) - timedelta(hours=2))
        year = self.years()['2024']
        # In the field on it too, the operation is not one attended as AHC only.
        self.assertEqual((year.ahc_days, year.ahc_events, year.ahc_hours, year.hours['operation']), (0, 0, 2, 6))
        self.assertEqual([label for _, label in self.panel('Operations')['key']], ['Other attendance', 'as AHC'])

    def test_each_key_names_the_colours_its_panel_draws(self):
        self.make_event('operation', when(2024, 1, 10), ol=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.member])
        self.make_event('operation', when(2024, 3, 10), attended=[self.other], ahc=[self.member])
        self.make_event('training', when(2024, 3, 12), attended=[self.member], leaders='Ann (TL)')
        self.make_event('training', when(2024, 3, 14), attended=[self.member])
        self.make_event('meeting', when(2024, 4, 10), attended=[self.member])
        self.make_event('community', when(2024, 5, 10), attended=[self.member])
        _, views, _ = self.chart_asked_for()
        for series in views[0]['series']:
            drawn = {colour for cell in series['cells'] for measure in cell for colour, amount in measure['parts'] if amount}
            self.assertEqual({colour for colour, _ in series['key']}, drawn, series['label'])

    def test_a_key_names_only_what_its_panel_draws(self):
        # Every training led: no other attendance to name.
        self.make_event('training', when(2024, 3, 12), attended=[self.member], leaders='Ann (TL)')
        self.assertEqual([label for _, label in self.panel('Trainings')['key']], ['as TL or LL'])
        # In the field all day on one operation, and AHC for a while on another inside that time: no AHC day
        # or hours, but an operation attended only as AHC, drawn in the events column, and so named.
        self.make_event('operation', when(2024, 4, 10), attended=[self.member], hours=10)
        other = self.make_event('operation', when(2024, 4, 10) + timedelta(hours=2), attended=[self.other])
        Participant.objects.create(period=other.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 4, 10) + timedelta(hours=2),
                                   return_home_at=when(2024, 4, 10) + timedelta(hours=4))
        self.assertEqual([label for _, label in self.panel('Operations')['key']], ['Other attendance', 'as AHC'])

    def test_figures_say_days_and_events_by_the_unit_s_count(self):
        # "1 of 2 days": the noun goes with the whole, the 2.
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        self.make_event('training', when(2024, 4, 10), attended=[self.other])
        days, events, _ = self.panel('Trainings')['cells'][0]
        self.assertEqual((days['tip'][1], events['tip'][1]), (('1 of 2', 'days'), ('1 of 2', 'events')))

    def test_ahc_days_and_ahc_events_are_counted_apart(self):
        # One operation as AHC, across two days, and one the member missed: 2 AHC days, of 3 unit active days
        # (their own AHC day among them), and 1 AHC event, of 2.
        operation = self.make_event('operation', when(2024, 3, 10), attended=[self.other])
        Participant.objects.create(period=operation.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 11))
        self.make_event('operation', when(2024, 4, 10), attended=[self.other])
        days, events, _ = self.panel('Operations')['cells'][0]
        self.assertEqual((days['parts'][-1], days['total']), (('1-light', 2), 3))
        self.assertEqual((events['parts'], events['total']), ([('1-strong', 0), ('1', 0), ('1-light', 1)], 2))
        _, all_events, _ = self.panel('All')['cells'][0]
        self.assertEqual((all_events['total'], all_events['tip'][1]), (2, ('1 of 2', 'events')))
        self.assertEqual(dict(member_activity(self.member, NOW, member_entries(self.member), records_from(NOW))['table']['total']['cells'])['AHC days'], 2)

    def test_the_led_hours_line_is_the_hours_led(self):
        # Of a year's 10 hours of training, the 4 led are picked out.
        self.make_event('training', when(2024, 3, 10), attended=[self.member], leaders='Ann (TL)', hours=4)
        self.make_event('training', when(2024, 4, 10), attended=[self.member], hours=6)
        hours = self.panel('Trainings')['cells'][0][2]
        self.assertEqual(hours['tip'], ['2024', ('10.0', 'hours'), ('4.0', 'as TL or LL')])
        self.assertEqual(hours['parts'], [('1-strong', 4), ('1', 6)])
        # Hours led that add up to 27.55 read 27.6, as every hour does: one formatter.
        self.make_event('training', when(2024, 5, 10), attended=[self.member], leaders='Ann (TL)', hours=3.78)
        self.make_event('training', when(2024, 5, 12), attended=[self.member], leaders='Ann (TL)', hours=19.77)
        self.assertIn(('27.6', 'as TL or LL'), self.panel('Trainings')['cells'][0][2]['tip'])

    def test_figures_show_hours_to_one_decimal_as_the_table_does(self):
        self.make_event('community', when(2024, 1, 10), attended=[self.member], hours=0.5)
        hours = self.panel('Community')['cells'][0][2]['tip']
        self.assertEqual(hours, ['2024', ('0.5', 'hours')])
        self.assertEqual(member_activity(self.member, NOW, member_entries(self.member), records_from(NOW))['table']['total']['cells'][-1], ('Total', '1 / 0.5 hours'))

    def test_hours_as_ol_and_ahc_alone_leave_no_other_hours(self):
        # Half an hour as OL and forty minutes as AHC: taking both from the total
        # in floating point leaves -1e-16, which the chart would draw below zero.
        self.make_event('operation', when(2024, 1, 10), ol=[self.member], hours=0.5)
        ahc = self.make_event('operation', when(2024, 2, 10), attended=[self.other])
        Participant.objects.create(period=ahc.period_set.first(), member=self.member, ahc=True,
                                   en_route_at=when(2024, 2, 10),
                                   return_home_at=when(2024, 2, 10) + timedelta(minutes=40))
        hours = [cell[2]['parts'] for cell in self.panel('Operations')['cells']]
        self.assertEqual(hours, [[('1-strong', 0.5), ('1', 0), ('1-light', 40 / 60)]])
        self.assertEqual(activity_rows(self.member, NOW, member_entries(self.member), records_from(NOW))['total'].other_hours['operation'], 0)

    def test_chart(self):
        self.make_event('operation', when(2023, 1, 10), ol=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        self.make_event('training', when(2024, 3, 10), attended=[self.member], leaders='Ann')
        self.make_event('meeting', when(2024, 3, 10) + timedelta(hours=5), attended=[self.member])   # that evening
        measures, (years, months), options = self.chart_asked_for()
        self.assertEqual([series['label'] for series in years['series']],
                         ['All', 'Operations', 'Trainings', 'Meetings', 'Community'])
        self.assertEqual([p['short'] for p in years['periods']], ["'23", "'24"])
        self.assertEqual(len(months['periods']), 18)
        self.assertEqual([(m['label'], m['title']) for m in measures],
                         [('Days', 'Days attended / unit active days, by type, 2023 to 2024'),
                          ('Events', 'Events attended / unit events, by type, 2023 to 2024'),
                          ('Hours', 'Hours logged, by type, 2023 to 2024')])
        self.assertEqual(options['name'], 'activity')
        # Its question, and the switch's lead as on the unit report.
        self.assertEqual((options['note'], options['measure_switch_label']),
                         ('How often does this member take part, and how does that compare with the unit?', 'Count'))

        def key(label):
            return [name for _, name in self.panel(label)['key']]
        self.assertEqual(key('All'), ['Operations', 'Trainings', 'Meetings', 'Community'])
        # Only what each panel draws: every operation was as OL or as AHC, and every training led.
        self.assertEqual(key('Operations'), ['as OL', 'as AHC'])
        self.assertEqual(key('Trainings'), ['as TL or LL'])
        self.assertEqual(key('Meetings'), ['Attended'])

        def column(label, period, view=0):
            """For days, events and hours: (the parts that are not nothing, the whole, the figures)."""
            return [([part for part in cell['parts'] if part[1]], cell['total'], cell['tip'])
                    for cell in self.panel(label, view)['cells'][period]]
        # Leading at the foot in the darkest blue; AHC in the lightest.
        self.assertEqual(column('Operations', 0), [
            ([('1-strong', 1)], 1, ['2023', ('1 of 1', 'day'), (1, 'as OL')]),
            ([('1-strong', 1)], 1, ['2023', ('1 of 1', 'event'), (1, 'as OL')]),
            ([('1-strong', 4)], 4, ['2023', ('4.0', 'hours'), ('4.0', 'as OL')])])
        self.assertEqual(column('Operations', 1), [
            ([('1-light', 1)], 1, ['2024', ('1 of 1', 'day'), (1, 'as AHC')]),
            ([('1-light', 1)], 1, ['2024', ('1 of 1', 'event'), (1, 'as AHC')]),
            ([('1-light', 2)], 2, ['2024', ('2.0', 'hours'), ('2.0', 'as AHC')])])
        training = [([('1-strong', 1)], 1, ['2024', ('1 of 1', 'day'), (1, 'as TL or LL')]),
                    ([('1-strong', 1)], 1, ['2024', ('1 of 1', 'event'), (1, 'as TL or LL')]),
                    ([('1-strong', 4)], 4, ['2024', ('4.0', 'hours'), ('4.0', 'as TL or LL')])]
        self.assertEqual(column('Trainings', 1), training)
        # The same in the month it happened, the fifteenth of the months shown.
        self.assertEqual(column('Trainings', 14, view=1),
                         [(parts, whole, ['Mar 2024'] + tip[1:]) for parts, whole, tip in training])
        # A day with a training and a meeting counts once, as a training day;
        # the three events on those two days each count.
        self.assertEqual(column('All', 1), [
            ([('1-strong', 1), ('1', 1)], 2, ['2024', ('2 of 2', 'days')]),
            ([('1-strong', 1), ('1', 1), ('1-light', 1)], 3, ['2024', ('3 of 3', 'events')]),
            ([('1-strong', 2), ('1', 4), ('1-light', 4)], 10, ['2024', ('10.0', 'hours')])])

    def test_table(self):
        self.make_event('operation', when(2023, 1, 10), attended=[self.member])
        self.make_event('operation', when(2024, 2, 10), attended=[self.other], ahc=[self.member])
        for week in range(7):
            self.make_event('meeting', when(2024, 3, 11) + timedelta(weeks=week), attended=[self.member], hours=160)
        table = member_activity(self.member, NOW, member_entries(self.member), records_from(NOW))['table']
        self.assertEqual(table['columns'], ['Operations', 'AHC days', 'Trainings', 'Meetings', 'Community', 'Total'])
        # Each cell carries its column's heading, for a screen too narrow for columns.
        self.assertEqual(table['rows'][0]['cells'][0], ('Operations', '1 / 4.0 hours'))
        self.assertEqual([(r['label'], [c for _, c in r['cells'][:2]], r['cells'][-1][1]) for r in table['rows']], [
            ('2023', ['1 / 4.0 hours', ''], '1 / 4.0 hours'),
            ('2024', ['1 / 2.0 hours', 1], '51 / 1,122.0 hours'),
        ])
        self.assertEqual(table['total']['cells'][-1], ('Total', '52 / 1,126.0 hours'))
        # Half hours show, and add up: two years of half an hour each make one hour.
        for year in (2021, 2022):
            self.make_event('community', when(year, 5, 1), attended=[self.member], hours=0.5)
        table = member_activity(self.member, NOW, member_entries(self.member), records_from(NOW))['table']
        self.assertEqual([dict(r['cells'])['Community'] for r in table['rows'][:2]], ['1 / 0.5 hours', '1 / 0.5 hours'])
        self.assertEqual(dict(table['total']['cells'])['Community'], '2 / 1.0 hours')
        # Duty columns appear only for duties the member has done.
        DoAvailable.objects.create(member=self.other, year=2024, quarter=1, week=3, assigned=True)
        self.make_event('operation', when(2024, 1, 10), ol=[self.other])
        self.assertEqual(member_activity(self.other, NOW, member_entries(self.other), records_from(NOW))['table']['columns'][:3],
                         ['Operations', 'OL days', 'DO wks'])


class ReportPagesTestCase(PageTestCase):
    def test_an_entrys_row_and_the_totals_round_its_hours_alike(self):
        # An hour and a quarter is 1.3 hours, half up as written, in the entry's row and in the table.
        self.make_event('training', when(2024, 3, 10), attended=[self.member], hours=1.25)
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>1.3</td>', html=True)
        self.assertContains(response, '1 / 1.3 hours')
        self.assertNotContains(response, '1.2')

    def test_hours_left_out_show_once_they_come_to_a_tenth(self):
        # A training from 1pm to 5pm and a meeting from 4:58pm to 6pm: the meeting's two minutes logged
        # twice count for the training, and round to nothing.
        training, meeting = self.make_event('training', when(2024, 3, 10)), self.make_event('meeting', when(2024, 3, 10))
        Participant.objects.create(period=training.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 10) + timedelta(hours=4))
        Participant.objects.create(period=meeting.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 3, 10) + timedelta(hours=3, minutes=58),
                                   return_home_at=when(2024, 3, 10) + timedelta(hours=5))
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>1.0</td>', html=True)
        self.assertNotContains(response, '(0.0)')

    def test_pages(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member, self.other])
        client = Client()
        client.force_login(self.other)
        response = client.get(self.member.get_absolute_url())
        self.assertContains(response, 'id="activityTbl"')
        self.assertContains(response, '<td>Operation (in the field)</td>', html=True)
        self.assertContains(response, '<td>10 Jan 2024</td>', html=True)     # dates as on the report
        # One link to the report, in the page's own menu near the top.
        self.assertContains(response, reverse('report_activity_member', args=[self.member.id]), count=1)
        self.make_event('training', when(2024, 2, 1), attended=[self.member], hours=24 * 8)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, 'Days attended / unit active days')
        self.assertContains(response, '<!DOCTYPE html>\n<html lang="en">')
        # The report is sent compressed to a browser that takes it.
        packed = client.get(reverse('report_activity_member', args=[self.member.id]), HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(packed.headers['Content-Encoding'], 'gzip')
        self.assertLess(len(packed.content), len(response.content) / 5)
        self.assertContains(response, '10 Jan 2024')
        # Hours left out are shown in parentheses: all of a mistake, and the
        # part of an entry under way that falls after today, after the part counted.
        self.assertContains(response, '<td>(192.0)</td>', html=True)
        under_way = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=under_way.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 16))
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>35.0 (13.0)</td>', html=True)
        # The glossary at the foot defines the terms, with what holds only on a member's report.
        self.assertContains(response, '<tr><th>Term</th><th>Meaning</th></tr>', html=True)
        # Each table's title is its caption, and each row is named by its first cell.
        self.assertContains(response, '<caption>Days attended / hours logged</caption>', html=True)
        self.assertContains(response, '<caption>Operations</caption>', html=True)
        self.assertContains(response, '<th scope="row">Total</th>', html=True)
        self.assertContains(response, '<th scope="row">Unit active day</th>', html=True)
        self.assertContains(response, 'own days attended count too.')
        self.assertContains(response, 'Hours left out, and time counted on another row, are shown in parentheses.')
        self.assertContains(response, 'counts once, for the one that began first.')
        # Two rows hold only on a member's report: what an AHC day is, and how the All panel counts a day.
        self.assertContains(response, '<th scope="row">AHC days</th>', html=True)
        self.assertContains(response, 'under the first of Operations, Trainings, Meetings and Community.')
        self.assertNotIn('AHC days', dict(glossary()))
        self.assertContains(response, 'no hours are logged for administrative work or DO duty.')
        self.assertNotContains(response, 'Days*')
        unit = dict(glossary())
        self.assertNotIn('On this report', unit['Unit active day'] + unit['Unit event'])
        self.assertNotIn('parentheses', unit['Mistaken times'])
        self.assertTrue(unit['Mistaken times'].startswith('More than {} days'.format(report_settings().MAX_ENTRY_DAYS)))
        trainee = self.make_member('Dee', 'T')
        response = client.get(trainee.get_absolute_url())
        self.assertNotContains(response, 'id="activityTbl"')
        response = client.get(reverse('report_activity_member', args=[trainee.id]))
        self.assertEqual(response.status_code, 200)

    def test_the_activity_summary_keeps_its_own_styling(self):
        # The new reports' chart frame and glossary rules are theirs; the summary has only its tables'.
        client = Client()
        client.force_login(self.other)
        summary = client.get('/reports/activity-summary/?start=2024-01-01&end=2024-12-31')
        self.assertContains(summary, 'tr.member:nth-child(even)')
        self.assertNotContains(summary, '.chart')
        self.assertNotContains(summary, 'glossary')
        report = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(report, '.chart-head { background-color: #ccc;')

    def test_report_with_an_unknown_type_of_event(self):
        event = self.make_event('meeting', when(2024, 1, 10), attended=[self.member])
        Event.objects.filter(pk=event.pk).update(type='other')
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        # It is not counted, so there is nothing to show, not a year of zeros.
        self.assertNotIn(event, reported_events())
        self.assertIsNone(activity_rows(self.member, NOW, member_entries(self.member), records_from(NOW)))
        self.assertNotContains(response, 'class="chart"')
