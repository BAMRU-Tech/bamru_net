from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, Http404
from django.template import loader
from django.utils import timezone
from django.views import generic, View

from main.models import Member, Event, Period

import collections
import csv
import dateutil.parser
import io
import os
import tempfile
import vobject
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta

import logging
logger = logging.getLogger(__name__)


class ReportListView(generic.base.TemplateView):
    template_name = 'reports/index.html'


class BaseReportView(View):
    def render(self, report_filename, context):
        report_name, report_filetype = report_filename.rsplit('.', 1)

        try:
            template = loader.get_template('reports/{}.html'.format(report_name))
        except loader.TemplateDoesNotExist:
            raise Http404

        context['report_filetype'] = report_filetype

        content = template.render(context, self.request)

        if report_filetype == 'html':
            return HttpResponse(content)
        else:
            raise Http404

def get_datetime_from_text(text, default):
    try:
        return timezone.make_aware(dateutil.parser.parse(text))
    except (TypeError, ValueError):
        return default

class ReportEventView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):
        type = request.GET.get('type', None)

        end = get_datetime_from_text(request.GET.get('end', None),
                                     timezone.now())
        start = get_datetime_from_text(request.GET.get('start', None),
                                       end - timedelta(days=365))

        members = Member.members.all()
        events = (Event.objects
                   .filter(start_at__gte=start,
                           start_at__lte=end)
                   .order_by('start_at')
        )
        periods = (Period.objects
                   .select_related('event')
                   .filter(event__start_at__gte=start,
                           event__start_at__lte=end)
                   .prefetch_related('participant_set')
        )
        if type:
            events = events.filter(type=type)
            periods = periods.filter(event__type=type)
        else:
            type = 'all'

        # tuples are [# attending, hours]
        type_totals = dict()
        event_type_count = dict()
        for t in Event.TYPES:
            type_totals[t[0]] = [0, 0]
            event_type_count[t[0]] = 0

        event_indicies = dict()
        event_totals = dict()
        for i, event in enumerate(events):
            event_indicies[event.id] = i
            event_totals = [0, 0]
            event_type_count[event.type] += 1

        member_table = dict()
        member_type_totals = dict()
        for member in members:
            member_table[member.id] = [0 for x in event_indicies]
            member_type_totals[member.id] = deepcopy(type_totals)
        for period in periods:
            event_index = event_indicies[period.event.id]
            for participant in period.participant_set.all():
                pid = participant.member.id
                if pid in member_table:  # exclude guests, etc
                    hours = participant.hours
                    if hours:
                        if member_table[pid][event_index] == 0:
                            member_type_totals[pid][period.event.type][0] += 1
                        member_type_totals[pid][period.event.type][1] += hours
                        member_table[pid][event_index] += hours

        unit_totals = [0, 0]
        for member in members:
            member.total_events = 0
            member.total_hours = 0
            member.type_totals = member_type_totals[member.id]
            for k, v in member.type_totals.items():
                member.total_events += v[0]
                member.total_hours += v[1]
                unit_totals[0] += v[0]
                unit_totals[1] += v[1]
                type_totals[k][0] += v[0]
                type_totals[k][1] += v[1]

        context = {}
        context['events'] = events
        context['members'] = members
        context['member_table'] = member_table
        context['unit_type_totals'] = type_totals
        context['unit_totals'] = unit_totals
        context['event_type_count'] = event_type_count
        context['event_total_count'] = sum(event_type_count.values())
        context['types'] = Event.TYPES
        context['type'] = type
        context['start'] = start
        context['end'] = end

        report_filename = 'activity-{}.html'.format(kwargs['activity_type'])
        return self.render(report_filename, context)


class ReportRosterView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):

        if (kwargs['roster_type'] == 'names.html'):
            status = Member.PRO_MEMBERS
        else:
            status = Member.CURRENT_MEMBERS

        context = {}
        context['members'] = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set',
                                  'emergencycontact_set')
                .filter(status__in=status)
                .order_by('last_name', 'first_name')
        )
        context['now'] = timezone.now()

        report_filename = 'BAMRU-' + kwargs['roster_type']
        return self.render(report_filename, context)


class ReportRosterCsvView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        buffer = io.StringIO()
        members = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set',
                                  'emergencycontact_set')
                .filter(status__in=Member.CURRENT_MEMBERS)
                .order_by('last_name', 'first_name')
        )

        writer = csv.writer(buffer)

        data = self.data_for_member(members.first())
        writer.writerow(data.keys())

        for member in members:
            data = self.data_for_member(member)
            writer.writerow(data.values())

        response = HttpResponse(buffer.getvalue())
        response['Content-Type'] = 'text/csv'
        return response

    def data_for_member(self, member):
        data = collections.OrderedDict()
        data['organization'] = 'BAMRU'
        data['roles'] = member.classic_roles
        data['first_name'] = member.first_name
        data['last_name'] = member.last_name
        data['mobile_phone'] = member.mobile_phone
        data['home_phone'] = member.home_phone
        data['work_phone'] = member.work_phone

        try:
            data['other_phone'] = member.phone_set.filter(type='Other').first().number
        except AttributeError:
            data['other_phone'] = ''

        try:
            data['home_address'] = member.address_set.filter(type='Home').first().oneline()
        except AttributeError:
            data['home_address'] = ''

        try:
            data['work_address'] = member.address_set.filter(type='Work').first().oneline()
        except AttributeError:
            data['work_address'] = ''

        try:
            data['other_address'] = member.address_set.filter(type='Other').first().oneline()
        except AttributeError:
            data['other_address'] = ''

        try:
            data['home_email'] = member.email_set.filter(type='Home').first().address
        except AttributeError:
            data['home_email'] = ''

        data['personal_email'] = member.personal_email
        data['work_email'] = member.work_email
        data['ham'] = member.ham
        data['v9'] = member.v9

        return data


class ReportRosterVcfView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        members = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set')
                .filter(status__in=Member.CURRENT_MEMBERS)
                .order_by('last_name', 'first_name')
        )
        cards = [self.vcard_for_member(m) for m in members]

        response = HttpResponse(''.join([c.serialize() for c in cards]))
        response['Content-Type'] = 'text/vcard'
        return response

    def vcard_for_member(self, member):
        card = vobject.vCard()
        # This mapping of last/first to family/given is not quite correct, but
        # we don't have the data to do better (and as far as I know it's right
        # for current BAMRU members).
        card.add('n').value = vobject.vcard.Name(
            family=member.last_name, given=member.first_name)
        card.add('fn').value = member.full_name
        card.add('org').value = ["BAMRU"]
        card.add('title').value = member.classic_roles
        for address in member.address_set.all():
            a = vobject.vcard.Address()
            a.street = '\n'.join(address.address_lines())
            a.city = address.city
            a.region = address.state
            a.code = address.zip

            adr = card.add('adr')
            adr.type_param = address.type
            adr.value = a
        for phone in member.phone_set.all():
            p = card.add('tel')
            p.type_param = phone.type
            p.value = phone.number
        for email in member.email_set.all():
            e = card.add('email')
            e.type_param = email.type
            e.value = email.address
        if member.ham:
            card.add('note').value = "Ham License - {}".format(member.ham)
        if member.v9:
            card.add('note').value = "V9 - {}".format(member.v9)
        return card
