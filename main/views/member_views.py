from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from main.models import Cert, Member, Unavailable

from django.forms.widgets import Select, Widget, SelectDateWidget

from datetime import timedelta
import datetime

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape


class MemberIndexView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.order_by('id')


class MemberDetailView(LoginRequiredMixin, generic.DetailView):
    model = Member
    template_name = 'member_detail.html'


class MemberCertsView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_cert_list.html'
    context_object_name = 'cert_list'

    def get_queryset(self):
        qs = Cert.objects.filter(member=self.kwargs['pk'])
        qs = qs.order_by(Cert.type_order_expression(), '-expiration', '-id')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = Member.objects.filter(id=self.kwargs['pk']).first()
        return context


class CertListView(LoginRequiredMixin, generic.ListView):
    template_name = 'cert_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        # 0 = cert
        # 1 = count
        cert_lookup = {}
        for idx, t in enumerate(Cert.TYPES):
            cert_lookup[t[0]] = idx
        qs = Member.members.prefetch_related('cert_set')
        for m in qs:
            m.certs = [{'cert':None, 'count':0} for x in cert_lookup]
            #m.cert_count = cert_count.copy()
            for c in m.cert_set.all():
                idx = cert_lookup[c.type]
                prev = m.certs[idx]['cert']
                # Choose when to replace the existing one in the list
                if ((not prev) or
                    (not prev.position) or
                    ((prev.position > c.position) and
                     (prev.is_expired or not c.is_expired)) or
                    (prev.is_expired and not c.is_expired)
                ):
                    m.certs[idx]['cert'] = c
                m.certs[idx]['count'] += 1
                #m.cert_count[idx] += 1
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['headers'] = [x[1] for x in Cert.TYPES]
        return context


class UnavailableListView(LoginRequiredMixin, generic.ListView):
    template_name = 'unavailable_list.html'
    context_object_name = 'member_list'

    # TODO split this into a Mixin shared with DoAbstractView
    def get_date_param(self, name):
        today = timezone.now().today().date()
        val = self.request.GET.get(name, '')
        setattr(self, name, int(val) if val.isnumeric() else getattr(today,name))

    def get_params(self):
        self.get_date_param('year')
        self.get_date_param('month')
        self.get_date_param('day')
        self.days = int(self.request.GET.get('days', 5))
        self.date = datetime.date(self.year, self.month, self.day)

    def get_queryset(self):
        self.get_params()
        today = self.date
        unavailable_set = Unavailable.objects.filter(
            end_on__gte=today).order_by('start_on')
        qs = Member.objects.prefetch_related(
            Prefetch('unavailable_set',
                     queryset=unavailable_set,
                     to_attr='unavailable_filtered')
        ).order_by('id')
        for m in qs:
            m.days = [('',1) for x in range(self.days)]
            for u in m.unavailable_filtered:
                if u.start_on >= today + timedelta(days=self.days):
                    continue  # starts off the screen
                if u.start_on <= today:
                    start = 0
                else:
                    start = (u.start_on - today).days

                # Add one to include the end day
                end_delta = (u.end_on - today).days + 1
                if end_delta > self.days:
                    end_delta = self.days
                    m.end_date = u.end_on

                comment = u.comment
                if not comment:
                    comment = 'BUSY'
                for day in range(start, end_delta):
                    m.days[day] = (comment, end_delta-start)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['days'] = self.days
        context['headers'] = [self.date + timedelta(days=d)
                              for d in range(self.days)]
        return context

class UnavailableEditView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'unavailable_form.html'

    def post(self, *args, **kwargs):
        return self.get(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        UnavailableFormSet = modelformset_factory(
            Unavailable,
            fields=['start_on', 'end_on', 'comment',],
        )

        qs = Unavailable.objects.filter(member=self.request.user)

        if self.request.method == 'POST':
            formset = UnavailableFormSet(self.request.POST)
            if formset.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.member = self.request.user
                    instance.save()
        else:
            formset = UnavailableFormSet(
                queryset=qs)
        context['formset'] = formset
        return context
