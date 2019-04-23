from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import ModelForm, modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from django.forms import widgets
from django.forms.widgets import HiddenInput, Select, Widget, SelectDateWidget

from main.lib.gcal import get_gcal_manager
from main.models import Member, Event, Participant, Period
from main.views.api_views import EventFilter

from datetime import timedelta
import datetime

import logging
logger = logging.getLogger(__name__)

from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape


class EventListView(LoginRequiredMixin, generic.ListView):
    """ This view does not do anything anymore, left as an example of a simple view """ 
    template_name = 'event_list.html'
    context_object_name = 'event_list'

    def get_queryset(self):
        """Example: create query set """
        return None

    def get_context_data(self, **kwargs):
        """Example: adding to the context, in addition to the query set """
        context = super().get_context_data(**kwargs)
        return context
        # Add column sort for datatable (zero origin)
        #context['sortOrder'] = '4, "asc"'
        #return context


# Explicitly does NOT include LoginRequiredMixin since this is public
# DO NOT COPY THE LINE BELOW FOR OTHER USES!
class EventPublishedListView(generic.ListView):
    template_name = 'event_published_list.html'
    context_object_name = 'event_list'

    def get_queryset(self):
        f = EventFilter(self.request.GET,
                        queryset=Event.objects.filter(
                            published=True).order_by('start_at'))
        return f.qs


class EventDetailView(LoginRequiredMixin, generic.DetailView):
    model = Event
    template_name = 'event_detail.html'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        obj.add_period(True)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        result = []
        try:
            for leader in context['event'].leaders.split(','):
                try:
                    id = Member.objects.filter(username=leader.strip().lower()).first().id
                except:
                    id = 0
                result.append({ 'name': leader, 'id': id })
        except:
            result.append({ 'name': 'TBD', 'id': 0})

        context['leaders'] = result
        return context

class EventForm(ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'description', 'type',
                  'location', 'lat', 'lon', 'leaders',
                  'start_at', 'finish_at',
                  'all_day', 'published',
                  ]
        field_classes = {
            'start_at': forms.SplitDateTimeField,
            'finish_at': forms.SplitDateTimeField,
        }
        widgets = {
            'start_at': forms.SplitDateTimeWidget(
                time_format='%H:%M',
                date_attrs={'type': 'date', 'pattern': '[0-9]{4}-[0-9]{2}-[0-9]{2}',
                            'oninvalid': "this.setCustomValidity('Enter valid date yyyy-mm-dd')"},
                time_attrs={'type': 'time', 'pattern': '[0-9]{2}:[0-9]{2}',
                            'oninvalid': "this.setCustomValidity('Enter valid time 24H: hh:mm')"},
            ),
            'finish_at': forms.SplitDateTimeWidget(
                time_format='%H:%M',
                date_attrs={'type': 'date', 'pattern': '[0-9]{4}-[0-9]{2}-[0-9]{2}',
                            'oninvalid': "this.setCustomValidity('Enter valid date yyyy-mm-dd')"},
                time_attrs={'type': 'time', 'pattern': '[0-9]{2}:[0-9]{2}',
                            'oninvalid': "this.setCustomValidity('Enter valid time 24H: hh:mm')"},
            ),
            'lat': widgets.HiddenInput(),
            'lon': widgets.HiddenInput(),
                
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_at')
        finish = cleaned_data.get('finish_at')
        if finish and finish < start:
            self.add_error('finish', 'Finish time must not be earlier than start time')
        return cleaned_data


class EventUpdateView(LoginRequiredMixin, generic.edit.UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'event_create.html'

    def get_form(self):
        form = super(EventUpdateView, self).get_form()

        # Mark required fields
        form.fields['title'].label = "Title*"
        form.fields['type'].label = "Type*"
        form.fields['location'].label = "Location*"
        form.fields['start_at'].label = "Start*"

        return form

    # Abuse get_success_url to do a calendar update after updating the object.
    def get_success_url(self, *args, **kwargs):
        get_gcal_manager().sync_event(self.object)
        return super(EventUpdateView, self).get_success_url(*args, **kwargs)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Update'
        return context


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
        form.fields['start_at'].label = "Start*"

        type = self.request.GET.get('type')
        form.fields['type'].initial = type
        form.fields['description'].widget.attrs = { 'rows':4 }

        return form

    # Abuse get_success_url to do a calendar update after creating the object.
    def get_success_url(self, *args, **kwargs):
        get_gcal_manager().sync_event(self.object)
        return super(EventCreateView, self).get_success_url(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['action'] = 'Create'
        return context


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
        period_id = self.kwargs.get('period')
        members = (Member.members.filter(status__in=Member.AVAILABLE_MEMBERS)
                   .exclude(participant__period=period_id))
        return members

    def get_success_url(self):
        return self.object.period.event.get_absolute_url()

    def get_initial(self):
        period = get_object_or_404(Period, pk=self.kwargs.get('period'))
        return {
            'period':period,
        }
