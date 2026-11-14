"""What the tests of counting and of the pages that show it share: a fixed now, a time of day that stays in one
local day, and a member and another to log time with."""
from unittest import mock
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone

from main.lib.activity import member_activity
from main.lib.counting import (activity_rows, member_entries, member_latest, operations_not_run, operations_that_ran,
                               records_from, reply_templates_from)
from main.models import Event, Member, Message, Participant, Period, RsvpTemplate


NOW = datetime(2024, 6, 15, 20, 0, tzinfo=dt_timezone.utc)


def when(year, month, day):
    """20:00 UTC, the middle of the day in Pacific time (noon in winter, 1pm in
    summer), so short events stay within one local day."""
    return datetime(year, month, day, 20, 0, tzinfo=dt_timezone.utc)


def every_operation():
    """Every operation's id, for a test that asks about them all."""
    return Event.objects.filter(type='operation').values_list('id', flat=True)


class ActivityTestCase(TestCase):
    def setUp(self):
        self.member = self.make_member('Ann', 'FM')
        self.other = self.make_member('Bob', 'FM')

    def make_member(self, name, status):
        return Member.objects.create(first_name=name, last_name='Test',
                                     username=name.lower(), status=status)

    def make_event(self, event_type, start, attended=(), no_time=(), ahc=(), ol=(), hours=4,
                   leaders=''):
        """Create a one-period event. `attended` and `ol` members log `hours`
        (the `ol` ones flagged OL); `no_time` members are listed without times;
        `ahc` members log two hours as AHC."""
        event = Event.objects.create(type=event_type, title='Event', location='Here', leaders=leaders,
                                     start_at=start, finish_at=start + timedelta(hours=hours))
        # Saving an event creates its first period.
        period = event.period_set.first() or Period.objects.create(event=event, position=1)
        for member in list(attended) + list(ol):
            Participant.objects.create(period=period, member=member, ol=member in ol,
                                       en_route_at=start,
                                       return_home_at=start + timedelta(hours=hours))
        for member in no_time:
            Participant.objects.create(period=period, member=member)
        for member in ahc:
            Participant.objects.create(period=period, member=member, ahc=True, en_route_at=start,
                                       return_home_at=start + timedelta(hours=2))
        return event

    def years(self, member=None):
        member = member or self.member
        return {str(row.period): row for row in activity_rows(member, NOW, member_entries(member), records_from(NOW))['years']}

    def days(self, row, event_type):
        """(days attended, unit active days)"""
        return row.days[event_type], row.active_days[event_type]

    def chart_asked_for(self, member=None):
        """What the report gives the chart component to draw, not what that makes
        of it: (measures, views, options), as passed to charts.share_panels."""
        member = member or self.member
        with mock.patch('main.lib.activity.charts.share_panels') as share_panels:
            member_activity(member, NOW, member_entries(member), records_from(NOW))
        (measures, views), options = share_panels.call_args
        return measures, views, options

    def panel(self, label, view=0, member=None):
        """One panel as the report asks for it: {'label', 'key', 'cells'}, each
        cell a column for days, events and hours with its parts and its figures."""
        _, views, _ = self.chart_asked_for(member)
        return next(series for series in views[view]['series'] if series['label'] == label)

    def latest(self, member=None):
        return {i['label']: i for i in member_latest(member or self.member, NOW)}

    def not_run(self):
        """Why each operation that did not run by NOW did not: {id: 'heads_up' or 'called_off'}."""
        ran = operations_that_ran(NOW, every_operation())
        return {event_id: not_run.why for event_id, not_run in operations_not_run(NOW, ran, reply_templates_from()).items()}

    def paging_began(self, pages=date(2016, 8, 9), templates=date(2019, 2, 13)):
        """Pages for operations recorded from the local day `pages`, and saying whether they were a callout
        or a heads-up from `templates`, as the reports read them from the first of each: here the pages of
        an operation still to start, which no report counts yet."""
        # ActivityTestCase's own make_event, as a test case may page the events its own makes.
        first = ActivityTestCase.make_event(self, 'operation', NOW + timedelta(days=365))
        for day, template in ((pages, None), (templates, RsvpTemplate.objects.get_or_create(name='Heads Up')[0])):
            page = Message.objects.create(author=self.other, text='Page', format='page',
                                          period=first.period_set.first(), rsvp_template=template)
            Message.objects.filter(id=page.id).update(created_at=timezone.make_aware(datetime.combine(day, time(12))))

    def paged(self, event, template):
        """A page for `event`, sent as it started, asking who can go ('Available?') or warning ('Heads Up')."""
        page = Message.objects.create(author=self.other, text='Page', format='page', period=event.period_set.first(),
                                      rsvp_template=RsvpTemplate.objects.get_or_create(name=template)[0])
        Message.objects.filter(id=page.id).update(created_at=event.start_at)


class PageTestCase(ActivityTestCase):
    """For tests of the pages, which read the clock: it is held at NOW, so that they do not grow as the tests age."""

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch('django.utils.timezone.now', return_value=NOW))
