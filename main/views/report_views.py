from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F
from django.http import HttpResponse, Http404
from django.template import loader
from django.utils import timezone
from django.views import generic, View

from main.models import Cert, Member, MemberStatusType, Event, Participant, Period

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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['start'] = timezone.now() - timedelta(days=365)
        context['end'] = timezone.now()
        return context


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
                   .prefetch_related('participant_set__member')
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


class ReportEventMemberView(LoginRequiredMixin, generic.DetailView):
    model = Member
    template_name = 'reports/activity-member.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = {}
        for t in Event.TYPES:
            events[t] = (Participant.objects
                         .filter(member__id=self.kwargs['pk'], period__event__type=t[0])
                         .order_by('period__event__start_at', 'period__position'))
        context['events'] = events
        return context


class CertExpireView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):

        type = request.GET.get('type', None)

        end = get_datetime_from_text(request.GET.get('end', None),
                                     timezone.now())
        start = get_datetime_from_text(request.GET.get('start', None),
                                       end - timedelta(days=365))


        certs = Cert.objects.filter(
            expires_on__gte=start,
            expires_on__lte=end,
        ).select_related('member')
        if type is not None:
            certs = certs.filter(type=type)

        context = {}
        context['certs'] = certs
        context['types'] = Cert.TYPES
        context['type'] = type
        context['start'] = start
        context['end'] = end
        return self.render('cert-expire.html', context)


class ReportRosterView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):

        if (kwargs['roster_type'] == 'names.html'):
            status = [t.short for t in MemberStatusType.objects.filter(
                is_pro_eligible=True)]
        else:
            status = [t.short for t in MemberStatusType.objects.filter(
                is_current=True)]

        context = {}
        context['members'] = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set', 'role_set',
                                  'emergencycontact_set')
                .select_related('status')
                .filter(status__short__in=status)
                .order_by('last_name', 'first_name')
        )
        context['now'] = timezone.now()

        report_filename = 'BAMRU-' + kwargs['roster_type']
        return self.render(report_filename, context)


class ReportRosterCsvView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        buffer = io.StringIO()
        members = (
            Member.members
                .prefetch_related('address_set', 'phone_set', 'email_set',
                                  'emergencycontact_set', 'role_set')
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

        phones = member.grouped_phones()
        def maybe_number(t):
            try:
                return phones[t][0].display_number
            except IndexError:
                return ''
        data['mobile_phone'] = maybe_number('Mobile')
        data['home_phone'] = maybe_number('Home')
        data['work_phone'] = maybe_number('Work')
        data['other_phone'] = maybe_number('Other')

        addresses = member.grouped_addresses()
        def maybe_address(t):
            try:
                return addresses[t][0].oneline()
            except IndexError:
                return ''
        data['home_address'] = maybe_address('Home')
        data['work_address'] = maybe_address('Work')
        data['other_address'] = maybe_address('Other')

        emails = member.grouped_emails()
        def maybe_email(t):
            try:
                return emails[t][0].address
            except IndexError:
                return ''
        data['home_email'] = maybe_email('Home')
        data['personal_email'] = maybe_email('Personal')
        data['work_email'] = maybe_email('Work')

        data['ham'] = member.ham
        data['v9'] = member.v9

        return data


class ReportRosterVcfView(LoginRequiredMixin, View):
    def get(self, request, **kwargs):
        members = (
            Member.members
                .prefetch_related('address_set', 'phone_set', 'email_set', 'role_set')
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


class ReportEventErrorsView(LoginRequiredMixin, View):
    def errors(self, participants, message):
        return self.messages('Error', participants, message)

    def warnings(self, participants, message):
        return self.messages('Warning', participants, message)

    def messages(self, severity, participants, message):
        return ['{} - {} in {} {} for {}: {}'.format(
            p.period.event.start_at, severity, p.period.event.type,
            p.period, p.member, message)
                for p in participants]

    def get(self, request, *args, **kwargs):
        max_hours = 48
        errors = []
        participants = Participant.objects.filter(
            period__event__finish_at__lt=timezone.now(),
            period__event__start_at__gt=timezone.now() - timedelta(days=400),
        ).select_related('member', 'period__event')
        errors += self.errors(participants.filter(
            en_route_at__isnull=True,
            return_home_at__isnull=False,
            ), 'No departure time')
        errors += self.errors(participants.filter(
            en_route_at__isnull=False,
            return_home_at__isnull=True,
            ), 'No return time')
        errors += self.errors(participants.filter(
            signed_in_at__isnull=True,
            signed_out_at__isnull=False,
            ), 'No sign in time')
        errors += self.errors(participants.filter(
            signed_in_at__isnull=False,
            signed_out_at__isnull=True,
            ), 'No sign out time')
        errors += self.errors(participants.filter(
            en_route_at__gt=F('return_home_at'),
            ), 'Departed home after returned home')
        errors += self.errors(participants.filter(
            signed_in_at__gt=F('signed_out_at'),
            ), 'Sign in after sign out')
        errors += self.warnings(participants.filter(
            en_route_at__isnull=True,
            return_home_at__isnull=True,
            signed_in_at__isnull=True,
            signed_out_at__isnull=True,
            ), 'No times recorded')
        errors += self.warnings(participants.filter(
            return_home_at__gt=F('en_route_at') + timedelta(hours=max_hours),
            ), 'Departure-to-return duration > {} hours'.format(max_hours))
        response = '<h1>Event errors:</h1>'
        response += '<br>\n'.join(sorted(errors, reverse=True))
        return HttpResponse(response)
