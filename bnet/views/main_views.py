from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse
from django.utils import timezone
from django.views import generic
from bnet.models import DoAvailable, Event, Member, Participant, Period

from django.forms.widgets import Select, Widget, SelectDateWidget

from datetime import datetime, timedelta

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


class EventIndexView(LoginRequiredMixin, generic.ListView):
    """ Render current event list """
    template_name = 'event_list.html'
    context_object_name = 'event_list'

    def get_queryset(self):
        """Return current event list """
        qs = Event.objects.all()
        upcoming = qs.filter(start__gte=datetime.today()) \
                     .exclude(start__gte=datetime.today() + timedelta(days=14))
        recent = qs.filter(start__lt=datetime.today()) \
                   .exclude(start__lt=datetime.today() - timedelta(days=30))
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
        qs = qs.filter(start__gte=datetime.today() - timedelta(days=365))
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
