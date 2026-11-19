"""A member's activity report: its chart and table (main.lib.activity), and the page."""
import gzip
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import Client
from django.urls import reverse

from main.lib import counting
from main.lib.activity import glossary, member_activity
from main.lib.charts import hours_text
from main.lib.counting import activity_rows, member_entries, records_from, reported_events
from main.lib.report_settings import report_settings
from main.models import DoAvailable, Event, Member, Participant, Period
from main.tests.helpers import NOW, ActivityTestCase, PageTestCase, when


# How a row of the lists marks hours the totals do not add, and the lines under a list that has them.
ELSEWHERE = ('<span class="not-added"><span aria-hidden="true">†</span>'
             '<span class="visually-hidden">counted on another row: </span>{}</span>')
LEFT_OUT = ('<span class="not-added"><span aria-hidden="true">‡</span>'
            '<span class="visually-hidden">left out of the totals: </span>{}</span>')
ELSEWHERE_NOTE = ('<p class="events-note">† Hours or days counted on another row, so not added here. See Hours and '
                  'days not added, below.</p>')
LEFT_OUT_NOTE = '<p class="events-note">‡ Hours left out of the totals. See Time left out, below.</p>'


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

    def test_the_all_panel_s_figures_break_its_column_down_by_type(self):
        # A day on an operation and two at trainings, one with a meeting that evening, which counts the day under
        # Trainings, as the column draws it; and none at community events, which has no line.
        self.make_event('operation', when(2024, 2, 10), attended=[self.member], hours=5)
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        self.make_event('training', when(2024, 4, 10), attended=[self.member])
        self.make_event('meeting', when(2024, 4, 10) + timedelta(hours=5), attended=[self.member], hours=2)
        self.make_event('training', when(2024, 5, 10), attended=[self.other])
        days, events, hours = self.panel('All')['cells'][0]
        # The head line gives the unit, so each line is the type alone, one word that never wraps.
        self.assertEqual(days['tip'], ['2024', ('3 of 4', 'days'), (1, 'operations'), (2, 'trainings')])
        self.assertEqual(events['tip'], ['2024', ('4 of 5', 'events'), (1, 'operation'), (2, 'trainings'),
                                         (1, 'meeting')])
        self.assertEqual(hours['tip'], ['2024', ('15.0', 'hours'), ('5.0', 'operations'), ('8.0', 'trainings'),
                                        ('2.0', 'meetings')])
        # And in the months: April's.
        days, events, hours = self.panel('All', view=1)['cells'][2]
        self.assertEqual((days['tip'], events['tip'], hours['tip']),
                         (['Apr 2024', ('1 of 1', 'day'), (1, 'trainings')],
                          ['Apr 2024', ('2 of 2', 'events'), (1, 'training'), (1, 'meeting')],
                          ['Apr 2024', ('6.0', 'hours'), ('4.0', 'trainings'), ('2.0', 'meetings')]))
        # And a community event: "community", in one word, for days, events and hours.
        self.make_event('community', when(2024, 5, 20), attended=[self.member])
        days, events, hours = self.panel('All', view=1)['cells'][3]
        self.assertEqual((days['tip'][2:], events['tip'][2:], hours['tip'][2:]),
                         ([(1, 'community')], [(1, 'community')], [('4.0', 'community')]))

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
                         [('Days', 'Days attended / unit active days, by type and role, 2023 to 2024'),
                          ('Events', 'Events attended / unit events, by type and role, 2023 to 2024'),
                          ('Hours', 'Hours logged, by type and role, 2023 to 2024')])
        self.assertEqual(options['name'], 'activity')
        # Its question, and the switch's lead as on the unit report.
        self.assertEqual((options['note'], options['measure_switch_label']),
                         ('How many days and events does this member attend, against the unit\'s, and how many hours do they log?',
                          'Count'))

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
            ([('1-strong', 1), ('1', 1)], 2, ['2024', ('2 of 2', 'days'), (1, 'operations'), (1, 'trainings')]),
            ([('1-strong', 1), ('1', 1), ('1-light', 1)], 3,
             ['2024', ('3 of 3', 'events'), (1, 'operation'), (1, 'training'), (1, 'meeting')]),
            ([('1-strong', 2), ('1', 4), ('1-light', 4)], 10,
             ['2024', ('10.0', 'hours'), ('2.0', 'operations'), ('4.0', 'trainings'), ('4.0', 'meetings')])])

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
                         ['Operations', 'OL days', 'DO weeks'])


class ReportPagesTestCase(PageTestCase):
    def test_the_two_report_pages_alone_are_sent_compressed(self):
        # To a browser that takes gzip each report comes packed, saying so and that it varies with what the
        # browser takes, and unpacks to the page as sent plain; to one that does not, plain. No other page is.
        self.paging_began()
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        client = Client()
        client.force_login(self.other)
        for url in (reverse('report_activity_member', args=[self.member.id]), reverse('report_activity_unit')):
            with self.subTest(url):
                plain, packed = client.get(url), client.get(url, HTTP_ACCEPT_ENCODING='gzip')
                self.assertNotIn('Content-Encoding', plain.headers)
                self.assertEqual(packed.headers['Content-Encoding'], 'gzip')
                self.assertIn('Accept-Encoding', packed.headers['Vary'])
                self.assertEqual(gzip.decompress(packed.content), plain.content)
        for url in (reverse('reports_list'), self.member.get_absolute_url(), reverse('event_list'), reverse('member_list')):
            with self.subTest(url):
                self.assertNotIn('Content-Encoding', client.get(url, HTTP_ACCEPT_ENCODING='gzip').headers)

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
        self.assertNotContains(response, 'class="not-added"')
        self.assertNotContains(response, 'class="events-note"')
        # Decided on the number, not on how it is written: the same where a tenth is written with a comma.
        with self.settings(LANGUAGE_CODE='de'):
            self.assertEqual((hours_text(1), hours_text(0)), ('1,0', '0,0'))
            response = client.get(reverse('report_activity_member', args=[self.member.id]))
            self.assertContains(response, '<td>1,0</td>', html=True)
            self.assertNotContains(response, 'class="not-added"')
            self.assertNotContains(response, 'class="events-note"')

    def test_the_page_works_out_its_entries_hours_once_for_the_lists_and_the_totals(self):
        self.make_event('training', when(2024, 3, 10), attended=[self.member])
        self.make_event('meeting', when(2024, 4, 10), attended=[self.member])
        client = Client()
        client.force_login(self.other)
        with mock.patch('main.lib.counting.entries_hours', wraps=counting.entries_hours) as entries_hours:
            response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertEqual(entries_hours.call_count, 1)
        self.assertContains(response, '1 / 4.0 hours')

    def test_the_glossary_explains_the_lists_when_there_is_nothing_to_chart(self):
        # Only time logged for a training still to come: no chart or table, but the list shows it marked left out,
        # a line under the list says what the mark means, and the glossary says more.
        self.make_event('training', NOW + timedelta(days=2), attended=[self.member])
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertIsNone(response.context['activity'])
        self.assertContains(response, '<td>{}</td>'.format(LEFT_OUT.format(hours_text(4))), html=True)
        self.assertContains(response, LEFT_OUT_NOTE, html=True)
        self.assertNotContains(response, ELSEWHERE_NOTE, html=True)
        self.assertContains(response, '<th scope="row">Time left out</th>', html=True)
        self.assertContains(response, '<th scope="row">† ‡ Hours and days not added</th>', html=True)

    def test_a_row_whose_time_ends_before_it_starts_shows_no_hours_and_no_mark(self):
        # Returned three hours before Left: no time, as the totals count it, not minus three hours left out.
        training = self.make_event('training', when(2024, 3, 10))
        Participant.objects.create(period=training.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 3, 10), return_home_at=when(2024, 3, 10) - timedelta(hours=3))
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>{}</td>'.format(hours_text(0)), html=True)
        self.assertNotContains(response, 'class="not-added"')
        self.assertNotContains(response, 'class="events-note"')
        self.assertNotContains(response, hours_text(-3))

    def test_the_guests_entry_names_guest_statuses_but_no_no_contact_one_whatever_the_statuses(self):
        # Another site's guest statuses, added to ours (the default bands name ours): the guest ones that are not
        # no-contact are named, in the order of Member.TYPES; with none of them, no names at all. What counts as a
        # guest is still GUESTS, no-contact or not.
        types = Member.TYPES + (('V', 'Visitor'), ('VX', 'Visitor Hidden'), ('O', 'Observer'))
        for guests, no_contact, said in (
                (('V', 'VX', 'O'), ('VX',), 'a guest status, such as Visitor or Observer.'),
                (('V', 'VX'), ('VX',), 'a guest status, such as Visitor.'),
                (('VX',), ('VX',), 'a guest status.'),
                (('V', 'O'), (), 'a guest status, such as Visitor or Observer.')):
            with self.subTest(guests=guests, no_contact=no_contact), \
                    mock.patch.object(Member, 'TYPES', types), mock.patch.object(Member, 'GUESTS', guests), \
                    mock.patch.object(Member, 'NO_CONTACT', no_contact):
                self.assertTrue(dict(glossary())['Guests'].startswith('Those whose status today is ' + said + ' Their'))

    def test_no_page_of_the_reports_names_a_no_contact_status(self):
        # Members of each no-contact status, with time beside a member's, and a guest's: the unit report, each one's
        # member report and the Activity section of their member page (the page's own status field is not the
        # reports') never say a no-contact status's name, nor its code as a word, in text, titles or labels.
        self.assertEqual(Member.NO_CONTACT, ('MN', 'GN'))
        names = [label for code, label in Member.TYPES if code in Member.NO_CONTACT]
        self.assertEqual(names, ['Member No-contact', 'Guest No-contact'])
        said = re.compile('|'.join([re.escape(n) for n in names] + [r'no.contact'] +
                                   [r'\b{}\b'.format(code) for code in Member.NO_CONTACT]), re.I)
        people = [self.make_member(name, status) for name, status in (('Mona', 'MN'), ('Gene', 'GN'), ('Gail', 'G'))]
        self.make_event('operation', when(2024, 3, 10), attended=[self.member, *people])
        self.make_event('training', when(2024, 4, 10), attended=[self.other, *people])
        client = Client()
        client.force_login(self.other)
        pages = {'unit report': client.get(reverse('report_activity_unit')).content.decode()}
        for person in people + [self.member]:
            pages['member report of ' + person.status] = client.get(
                reverse('report_activity_member', args=[person.id])).content.decode()
            page = client.get(person.get_absolute_url()).content.decode()
            start = page.index('<strong>Activity</strong>')
            pages['member page Activity of ' + person.status] = page[start:page.index('called off.</small></p>', start)]
        for name, page in pages.items():
            with self.subTest(name):
                self.assertIn('<th scope="row">Guests</th>' if 'report' in name else 'Training', page)
                self.assertEqual(said.findall(page), [])

    def test_the_lists_mark_hours_not_added_and_say_why_under_each_list_that_has_them(self):
        # Two periods of one operation, period 1 from 7:56am on Saturday 2 March 2024 to 5:27pm on Sunday, period 2
        # from 6am to 4:20pm on Sunday (PST, UTC-8): period 2's 10.3 hours are counted on period 1's row, and its
        # row marks them so; nothing in parentheses, which read as a negative number. A training with nothing
        # marked has no line under its list.
        operation = self.make_event('operation', when(2024, 3, 2))
        local = lambda day, hour, minute: datetime(2024, 3, day, hour, minute, tzinfo=dt_timezone.utc) + timedelta(hours=8)
        Participant.objects.create(period=operation.period_set.first(), member=self.member,
                                   en_route_at=local(2, 7, 56), return_home_at=local(3, 17, 27))
        Participant.objects.create(period=Period.objects.create(event=operation, position=2), member=self.member,
                                   en_route_at=local(3, 6, 0), return_home_at=local(3, 16, 20))
        self.make_event('training', when(2024, 4, 10), attended=[self.member])
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        # Period 1's row: its hours and its two days. Period 2's: its hours and its one day, both period 1's.
        self.assertContains(response, '<td>33.5</td><td>2</td>', html=True)
        self.assertContains(response, '<td>{}</td><td>{}</td>'.format(ELSEWHERE.format('10.3'), ELSEWHERE.format('1')),
                            html=True)
        self.assertContains(response, ELSEWHERE_NOTE, html=True, count=1)
        self.assertNotContains(response, LEFT_OUT_NOTE, html=True)
        self.assertNotContains(response, '(10.3)')
        # The line follows the operations' list, not the training's.
        page = response.content.decode()
        operations, trainings = page.index('<caption>Operations</caption>'), page.index('<caption>Trainings</caption>')
        self.assertLess(operations, page.index('class="events-note"'))
        self.assertLess(page.index('class="events-note"'), trainings)
        self.assertEqual(page.count('class="events-note"'), 1)
        # A row may show both: counted, another row's, and its own left out. An entry under way from 1pm on 14 June
        # to 1pm on the 16th, and a meeting from noon on the 16th to 3pm: the training's hour, and 2 after today.
        under_way = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=under_way.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 16))
        noon = self.make_event('meeting', when(2024, 6, 15))
        Participant.objects.create(period=noon.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 15) + timedelta(hours=23),
                                   return_home_at=when(2024, 6, 16) + timedelta(hours=2))
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>{} {}</td>'.format(ELSEWHERE.format('1.0'), LEFT_OUT.format('2.0')), html=True)
        self.assertContains(response, ELSEWHERE_NOTE, html=True, count=2)
        self.assertContains(response, LEFT_OUT_NOTE, html=True, count=2)

    def test_a_row_marks_its_days_counted_on_another_row_of_its_list(self):
        # Two trainings: 30 hours from 1pm on 20 March 2024, and 6pm on the 21st to 8pm on the 22nd. The second's
        # 21st is the first's day, its 22nd its own, and its first hour the first's: 25.0 †1.0 hours, 1 †1 days.
        # A meeting at 9pm on the 22nd, after the trainings, keeps its own day: a date counts once for each type.
        # Only the trainings' list has a line under it.
        earlier, later = self.make_event('training', when(2024, 3, 20)), self.make_event('training', when(2024, 3, 21))
        Participant.objects.create(period=earlier.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 3, 20), return_home_at=when(2024, 3, 20) + timedelta(hours=30))
        Participant.objects.create(period=later.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 3, 21) + timedelta(hours=5),
                                   return_home_at=when(2024, 3, 21) + timedelta(hours=31))
        self.make_event('meeting', when(2024, 3, 22) + timedelta(hours=8), attended=[self.member], hours=1)
        client = Client()
        client.force_login(self.other)
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>30.0</td><td>2</td>', html=True)
        self.assertContains(response, '<td>25.0 {}</td><td>1 {}</td>'.format(ELSEWHERE.format('1.0'), ELSEWHERE.format('1')),
                            html=True)
        self.assertContains(response, '<td>1.0</td><td>1</td>', html=True)
        self.assertContains(response, ELSEWHERE_NOTE, html=True, count=1)
        # The table's trainings: 3 days, as the list's own days add up to.
        entries = member_entries(self.member)
        self.assertEqual(activity_rows(self.member, NOW, entries, records_from(NOW))['total'].days['training'], 3)
        self.assertEqual(sum(e.days for e in counting.listed_entries(entries, NOW, records_from(NOW))
                             if e.entry.period.event.type == 'training'), 3)

    def test_pages(self):
        self.make_event('operation', when(2024, 1, 10), attended=[self.member, self.other])
        client = Client()
        client.force_login(self.other)
        response = client.get(self.member.get_absolute_url())
        self.assertContains(response, 'id="activityTbl"')
        self.assertContains(response, '<td>Operation (in the field)</td>', html=True)
        self.assertContains(response, '<td>10 Jan 2024</td>', html=True)     # dates as on the report
        self.assertContains(response, 'Dates are the last day attended, or for a stood-down line the day the operation '
                                      'began. As OL: in the field as Operation Leader, marked OL on the event page. '
                                      'Stood down: listed on an operation that was called off.')
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
        # Hours left out are marked ‡, which a screen reader reads as words: all of a mistake, and the
        # part of an entry under way that falls after today, after the part counted.
        self.assertContains(response, '<td>{}</td>'.format(LEFT_OUT.format('192.0')), html=True)
        under_way = self.make_event('training', when(2024, 6, 14))
        Participant.objects.create(period=under_way.period_set.first(), member=self.member,
                                   en_route_at=when(2024, 6, 14), return_home_at=when(2024, 6, 16))
        response = client.get(reverse('report_activity_member', args=[self.member.id]))
        self.assertContains(response, '<td>35.0 {}</td>'.format(LEFT_OUT.format('13.0')), html=True)
        # The glossary at the foot defines the terms, with what holds only on a member's report.
        self.assertContains(response, '<tr><th>Term</th><th>Meaning</th></tr>', html=True)
        # Each table's title is its caption, and each row is named by its first cell.
        self.assertContains(response, '<caption>Days attended / hours logged</caption>', html=True)
        self.assertContains(response, '<caption>Operations</caption>', html=True)
        self.assertContains(response, '<th scope="row">Total</th>', html=True)
        self.assertContains(response, '<th scope="row">Unit active day</th>', html=True)
        self.assertContains(response, "On a member&#x27;s own report, every day they attended counts as a unit active day "
                                      "too, even as AHC or as a guest, so the unit&#x27;s figure is never below theirs.")
        self.assertContains(response, '<th scope="row">† ‡ Hours and days not added</th>', html=True)
        self.assertContains(response, 'counts once, for the one that began first.')
        # Two rows hold only on a member's report: what an AHC day is, and how the All panel counts a day.
        self.assertContains(response, '<th scope="row">AHC days</th>', html=True)
        self.assertContains(response, 'under the first of Operations, Trainings, Meetings and Community.')
        self.assertNotIn('AHC days', dict(glossary()))
        self.assertNotContains(response, 'policies')
        glossed = dict(glossary(member_report=True))
        # Any time is a day, however short, and the day an entry's hours are shown with drops none of them.
        # Short sentences, an example after each rule: a date is a calendar date, a day attended what is counted.
        self.assertEqual(glossed['Day attended'],
                         'Any time logged for an event or operating period counts as at least one day attended, however '
                         'short: a one-hour meeting is a day. Up to 12 hours counts as one day, even if it runs past '
                         'midnight. That day is the date most of the time fell on: 10pm to 4am is one day, on the second '
                         'date. More than 12 hours counts each date with at least 2 hours on it: 6pm Saturday to 10am '
                         'Sunday is two days, and 8am Saturday to 1am Sunday is one day, Saturday. A date counts only '
                         'once for each type of event: two meetings on one date are one day. It also counts only once '
                         'across all types: a meeting and a training on one date are one day across all types.')
        self.assertEqual(glossed['Hours'],
                         "Hours of time logged on events; nothing else counts as hours. Each logged time's hours are "
                         'shown on the day or days it counts as (see Day attended). 10pm to 4am counts as one day, on '
                         'the second date, so all 6 hours are shown on that date. When a logged time has hours on a '
                         'date that does not count for it, they are added to the nearest date that does: for 8am '
                         'Saturday to 1am Sunday, all 17 hours are shown on Saturday. No hours are lost this way.')
        # The guest statuses named, but never a no-contact one (Member.NO_CONTACT).
        self.assertEqual(glossed['Guests'],
                         'Those whose status today is a guest status, such as Guest or Guest Alum. Their time counts '
                         'only on their own activity report. A former guest who is now a member counts as a member for '
                         'all their time, including time logged while they were a guest.')
        self.assertTrue(glossed['Logged time'].startswith('The time from Left to Returned on the event page, or from '
                                                          'Signed in to Signed out when Left or Returned is missing.'))
        self.assertIn('An event that has not started yet, and a day after today, count nothing yet; hours after the end '
                      'of today are left out.', glossed['Time left out'])
        # The roles named on the report, spelled out, and what leading is; DO weeks only where a member's report has them.
        self.assertTrue(glossed['OL'].startswith('Operation Leader'))
        self.assertTrue(glossed['AHC'].startswith('At Home Coordinator'))
        self.assertIn('On an operation, in the field as OL.', glossed['Led'])
        self.assertIn('in the month and year that hold most of its days; in its first three days, on today.',
                      glossed['DO weeks'])
        self.assertNotIn('DO weeks', dict(glossary()))
        # The Y-axis scale switch, on both reports' charts, named as the switch is.
        self.assertEqual(dict(glossary())['Y-axis scale'],
                         'Shared puts every panel of a chart on one scale, so their columns read against each other. '
                         "Separate gives each panel its own, so a small panel's columns show their shape.")
        self.assertNotIn('Scale', dict(glossary()))
        self.assertNotContains(response, 'Days*')
        unit = dict(glossary())
        self.assertNotIn('On this report', unit['Unit active day'] + unit['Unit event'])
        self.assertNotIn('parentheses', unit['Time left out'])
        self.assertNotIn('parentheses', glossed['Time left out'])
        self.assertNotIn('† ‡ Hours and days not added', unit)
        self.assertTrue(unit['Time left out'].startswith('More than {} days'.format(report_settings().MAX_ENTRY_DAYS)))
        self.assertNotIn('Mistaken times', unit)
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
