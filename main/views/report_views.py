from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, Http404
from django.template import loader
from django.utils import timezone
from django.views import View

from main.models import Member

import collections
import csv
import io
import os
import tempfile

import logging
logger = logging.getLogger(__name__)


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
        context = {}
        context['members'] = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set', 'emergencycontact_set')
                .filter(member_rank__in=Member.ACTIVE_RANKS)
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
                .prefetch_related('address_set', 'phone_set', 'email_set', 'emergencycontact_set')
                .filter(member_rank__in=Member.ACTIVE_RANKS)
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
        except Exception:
            data['other_phone'] = ''

        try:
            data['home_address'] = member.address_set.filter(type='Home').first().oneline()
        except Exception:
            data['home_address'] = ''

        try:
            data['work_address'] = member.address_set.filter(type='Work').first().oneline()
        except Exception:
            data['work_address'] = ''

        try:
            data['other_address'] = member.address_set.filter(type='Other').first().oneline()
        except Exception:
            data['other_address'] = ''

        try:
            data['home_email'] = member.email_set.filter(type='Home').first().address
        except Exception:
            data['home_email'] = ''

        try:
            data['personal_email'] = member.email_set.filter(type='Personal').first().address
        except Exception:
            data['personal_email'] = ''

        try:
            data['work_email'] = member.email_set.filter(type='Work').first().address
        except Exception:
            data['work_email'] = ''

        data['ham'] = member.ham
        data['v9'] = member.v9

        return data
