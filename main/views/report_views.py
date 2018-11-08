from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, Http404
from django.template import loader
from django.utils import timezone
from django.views import generic, View

from main.models import Member

import collections
import csv
import io
import os
import tempfile
import vobject

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


class ReportRosterView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):

        if (kwargs['roster_type'] == 'names.html'):
            ranks = Member.PRO_RANKS
        else:
             ranks = Member.CURRENT_RANKS

        context = {}
        context['members'] = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set',
                                  'emergencycontact_set')
                .filter(member_rank__in=ranks)
                .order_by('last_name', 'first_name')
        )
        import pdb; pdb.set_trace()
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
                .filter(member_rank__in=Member.CURRENT_RANKS)
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
                .filter(member_rank__in=Member.CURRENT_RANKS)
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
