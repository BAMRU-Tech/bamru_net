from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse
from django.utils import timezone
from django.views import generic
from bnet.models import DoAvailable, Event, Member, Participant, Period, Unavailable

from django.forms.widgets import Select, Widget, SelectDateWidget

from datetime import timedelta
import datetime

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape

class OrderListJson(BaseDatatableView):
    # The model we're going to show
    model = Member

    # define the columns that will be returned
    columns = ['last_name', 'member_rank', 'role', 'phone', 'email']
        
    # define column names that will be used in sorting
    # order is important and should be same as order of columns
    # displayed by datatables. For non sortable columns use empty
    # value like ''
    order_columns = ['last_name', 'member_rank', 'role', '', '']

    # set max limit of records returned, this is used to protect our site
    # if someone tries to attack our site and make it return huge amount of data
    max_display_length = 500

    def render_column(self, row, column):
        # We want to render user as a custom column
        return super(OrderListJson, self).render_column(row, column)

    def filter_queryset(self, qs):
        # use parameters passed in GET request to filter queryset

        # simple example:
        search = self.request.GET.get(u'search[value]', None)
        if search:
            qs = qs.filter(name__istartswith=search)

        # more advanced example using extra parameters
        filter_customer = self.request.GET.get(u'customer', None)

        if filter_customer:
            customer_parts = filter_customer.split(' ')
            qs_params = None
            for part in customer_parts:
                q = Q(customer_firstname__istartswith=part)|Q(customer_lastname__istartswith=part)
                qs_params = qs_params | q if qs_params else q
            qs = qs.filter(qs_params)
        return qs


class MemberIndexView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.order_by('id')


class MemberDetailView(LoginRequiredMixin, generic.DetailView):
    model = Member
    template_name = 'member_detail.html'


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

                for day in range(start, end_delta):
                    m.days[day] = (u.comment, end_delta-start)

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
                instances = formset.save()
        else:
            formset = UnavailableFormSet(
                queryset=qs)
        context['formset'] = formset
        return context

class EventIndexView(LoginRequiredMixin, generic.ListView):
    """ Render current event list """
    template_name = 'event_list.html'
    context_object_name = 'event_list'

    def get_queryset(self):
        """Return current event list """
        today = timezone.now().today()
        qs = Event.objects.all()
        upcoming = qs.filter(start__gte=today) \
                     .exclude(start__gte=today + timedelta(days=14))
        recent = qs.filter(start__lt=today) \
                   .exclude(start__lt=today - timedelta(days=30))
        qs = upcoming | recent
        return qs.order_by('start')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add column sort for datatable (zero origin)
        context['sortOrder'] = '4, "desc"'
        return context


class EventAllView(LoginRequiredMixin, generic.ListView):
    template_name = 'event_list.html'
    context_object_name = 'event_list'

    def get_queryset(self):
        """Return event list within the last year """
        qs = Event.objects.all()
        qs = qs.filter(start__gte=timezone.now().today() - timedelta(days=365))
        return qs.order_by('start')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add column sort for datatable (zero origin)
        context['sortOrder'] = '4, "asc"'
        return context


class EventDetailView(LoginRequiredMixin, generic.DetailView):
    model = Event
    template_name = 'event_detail.html'


class EventUpdateView(LoginRequiredMixin, generic.edit.UpdateView):
    model = Event
    fields = ['type', 'title', 'description',
              'location', 'leaders',
              'start', 'finish',
              'all_day', 'published',
              ]

    template_name = 'base_form.html'

    def get_form(self):
        '''add date picker in forms'''
        form = super(EventUpdateView, self).get_form()
        form.fields['start'].widget = SelectDateWidget()
        form.fields['finish'].widget = SelectDateWidget()
        return form


class EventCreateView(LoginRequiredMixin, generic.edit.CreateView): # In WIP
    model = Event
    fields = ['type', 'title', 'description',
              'location', 'leaders',
              'start', 'finish',
              'all_day', 'published',
              ]

    template_name = 'base_form.html'

    def get_form(self):
        '''add date picker in forms'''
        form = super(EventCreateView, self).get_form()
        form.fields['start'].widget = SelectDateWidget()
        form.fields['finish'].widget = SelectDateWidget()
        return form


class ParticipantCreateView(LoginRequiredMixin, generic.edit.CreateView):
    
    model = Participant
    fields = ['member', 'ahc', 'ol', 'period']
    template_name = 'base_form.html'

    def get_success_url(self):
        return self.object.period.event.get_absolute_url()

    def get_initial(self):
        period = get_object_or_404(Period, pk=self.kwargs.get('period'))
        return {
            'period':period,
        }


class ParticipantDeleteView(LoginRequiredMixin, generic.edit.DeleteView):
    model = Participant
    template_name = 'base_delete.html'

    def get_success_url(self):
        event = get_object_or_404(Event, pk=self.kwargs.get('event'))
        return event.get_absolute_url()
