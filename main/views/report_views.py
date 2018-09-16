from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template import loader
from django.utils import timezone
from django.views import View

from main.models import Member

import pdfkit
from pdfkit import PDFKit

import mock
import os
import tempfile

import logging
logger = logging.getLogger(__name__)


class BaseReportView(View):
    def render(self, report_filename, context):
        report_name, report_filetype = report_filename.rsplit('.', 1)

        template = loader.get_template('reports/{}.html'.format(report_name))
        # TODO: 404 if template doesn't exist

        content = template.render(context, self.request)

        if report_filetype == 'html':
            return HttpResponse(content)
        elif report_filetype == 'pdf':
            response = HttpResponse(pdfkit.from_string(content, None))
            response['Content-Type'] = 'application/pdf'
            return response


class ReportRosterView(LoginRequiredMixin, BaseReportView):
    def get(self, request, **kwargs):
        context = {}
        context['members'] = (
            Member.objects
                .prefetch_related('address_set', 'phone_set', 'email_set', 'emergencycontact_set')
                .filter(member_rank__in=Member.ACTIVE_RANKS)
                .order_by('last_name')
        )
        context['now'] = timezone.now()

        report_filename = 'BAMRU-' + kwargs['roster_type']
        return self.render(report_filename, context)
