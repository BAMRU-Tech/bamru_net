from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import ModelForm, modelformset_factory
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from django.forms import widgets
from main.models import Member, Event, Participant, Period

from django.forms.widgets import Select, Widget, SelectDateWidget

from datetime import timedelta
import datetime

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape

class EventImmediateView(LoginRequiredMixin, generic.ListView):
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

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        obj.add_period(True)
        return obj


class EventForm(ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'description', 'type',
                  'location', 'leaders',
                  'start', 'finish',
                  'all_day', 'published',
                  ]
        field_classes = {
            'start': forms.SplitDateTimeField,
            'finish': forms.SplitDateTimeField,
        }
        widgets = {
            'start': forms.SplitDateTimeWidget(
                time_format='%H:%M',
                date_attrs={'type': 'date'},
                time_attrs={'type': 'time'},
            ),
            'finish': forms.SplitDateTimeWidget(
                time_format='%H:%M',
                date_attrs={'type': 'date'},
                time_attrs={'type': 'time'},
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start')
        finish = cleaned_data.get('finish')
        if finish and finish < start:
            self.add_error('finish', 'Finish time must not be earlier than start time')
        return cleaned_data


class EventUpdateView(LoginRequiredMixin, generic.edit.UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'base_form.html'


class EventCreateView(LoginRequiredMixin, generic.edit.CreateView):
    model = Event
    form_class = EventForm
    template_name = 'event_create.html'

    def get_form(self):
        form = super(EventCreateView, self).get_form()

        # Mark required fields
        form.fields['title'].label = "Title*"
        form.fields['type'].label = "Type*"
        form.fields['location'].label = "Location*"
        form.fields['start'].label = "Start*"

        return form


class EventPeriodAddView(LoginRequiredMixin, generic.base.RedirectView):
    pattern_name = 'event_detail'
    def get_redirect_url(self, *args, **kwargs):
        e = get_object_or_404(Event, pk=kwargs.get('pk'))
        e.add_period()
        return super().get_redirect_url(*args, **kwargs)


class PeriodParticipantCreateView(LoginRequiredMixin, generic.ListView):    
    model = Participant
    fields = ['member', 'ahc', 'ol', 'period']
    context_object_name = 'member_list'
    template_name = 'period_participant_add.html'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.filter(
            Q(member_rank='TM') |
            Q(member_rank='FM') |
            Q(member_rank='T') |
            Q(member_rank='R') |
            Q(member_rank='S') |
            Q(member_rank='A')).order_by('id')

    def get_success_url(self):
        return self.object.period.event.get_absolute_url()

    def get_initial(self):
        period = get_object_or_404(Period, pk=self.kwargs.get('period'))
        return {
            'period':period,
        }
