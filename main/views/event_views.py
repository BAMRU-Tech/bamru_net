from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import ModelForm, modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from django.forms.widgets import HiddenInput, Select, Widget, SelectDateWidget

from dynamic_preferences.registries import global_preferences_registry

from main.lib.gcal import get_gcal_manager
from main.models import DoAvailable, Member, Event, Participant, Period
from main.views.api_views import EventFilter
from main import tasks

from datetime import timedelta
import datetime
import re

import logging
logger = logging.getLogger(__name__)

from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape

from django_q.tasks import async_task

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

    def get_queryset(self):
        return super().get_queryset().prefetch_related(
            Member.prefetch_unavailable('period_set__participant_set__member'),
            'period_set__participant_set__member__email_set',
            'period_set__participant_set__member__phone_set',
        )

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
                except Exception:
                    id = 0
                result.append({ 'name': leader, 'id': id })
        except Exception:
            result.append({ 'name': 'TBD', 'id': 0})

        context['leaders'] = result
        context['current_do'] = DoAvailable.current_scheduled_do()
        context['esb_spreadsheet_url'] = (
            global_preferences_registry.manager()['general__esb_spreadsheet_url'])
        return context

    def post(self, request, *args, **kwargs):
        event_id = self.get_object().id
        logger.info(request.POST)
        action = request.POST.get('action', None)
        if action == 'aar':
            logger.info('Calling event_create_aar {}'.format(event_id))
            async_task(tasks.event_create_aar, event_id)
            return HttpResponse('aar')
        if action == 'ahc_log':
            logger.info('Calling event_create_ahc_log {}'.format(event_id))
            async_task(tasks.event_create_ahc_log, event_id)
            return HttpResponse('ahc_log')
        if action == 'logistics_spreadsheet':
            logger.info('Calling event_create_logistics_spreadsheet {}'.format(event_id))
            async_task(tasks.event_create_logistics_spreadsheet, event_id)
            return HttpResponse('logistics_spreadsheet')
        return HttpResponseBadRequest('Error: No action set.')


# Latitude or longitude in decimal degrees, as a member types it: 37.7456 or -119.5936.
DEGREES = re.compile(r'[-+]?\d{1,3}(?:\.\d+)?')
# Both together, as a map copies them ("37.7456, -119.5936") or a Google Maps link holds them
# (".../@37.7456,-119.5936,15z").
LAT_LON = re.compile(r'([-+]?\d{1,3}\.\d+)\s*[,\s]\s*([-+]?\d{1,3}\.\d+)')
DEGREES_EXAMPLE = {'lat': '37.7456', 'lon': '-119.5936'}


def flip_sign(degrees):
    return degrees[1:] if degrees.startswith('-') else '-' + degrees.lstrip('+')


class EventForm(ModelForm):
    # Confirms a new point outside the team's usual area; a checkbox only once one is entered.
    point_is_right = forms.BooleanField(
        required=False, widget=HiddenInput, label='This point is right: save it anyway')

    class Meta:
        model = Event
        fields = ['title', 'description', 'description_private', 'type',
                  'location', 'location_private', 'lat', 'lon', 'point_is_right', 'leaders',
                  'start_at', 'finish_at',
                  'all_day', 'published',
                  ]
        labels = {'lat': 'Latitude', 'lon': 'Longitude'}
        help_texts = {
            'lat': 'Decimal degrees, such as 37.7456. A point copied from a map, such as '
                   '37.7456, -119.5936, can be pasted here to fill in both.',
            'lon': 'Decimal degrees, such as -119.5936. Longitude is negative west of Greenwich, '
                   'as all of California is.',
        }
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
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_at')
        finish = cleaned_data.get('finish_at')
        if finish and finish < start:
            self.add_error('finish_at', 'Finish time must not be earlier than start time')
        self.clean_lat_lon(cleaned_data)
        return cleaned_data

    def clean_lat_lon(self, cleaned_data):
        """Latitude and longitude in decimal degrees, both or neither. A new point outside the
        team's usual area is saved once the member confirms it, as it is most often a slip
        such as a missing minus sign."""
        lat, lon = cleaned_data.get('lat'), cleaned_data.get('lon')
        pasted = LAT_LON.search(lat or '')
        if pasted and not lon:
            lat, lon = pasted.groups()
            cleaned_data['lat'], cleaned_data['lon'] = lat, lon
        if not lat and not lon:
            return
        for name, value in (('lat', lat), ('lon', lon)):
            if not value:
                self.add_error(name, 'Enter both latitude and longitude, or neither.')
            elif not DEGREES.fullmatch(value):
                self.add_error(name, 'Enter decimal degrees, such as {}.'.format(DEGREES_EXAMPLE[name]))
        if self.has_error('lat') or self.has_error('lon'):
            return
        if abs(float(lat)) > 90:
            self.add_error('lat', 'Latitude and longitude look swapped.' if abs(float(lon)) <= 90
                           else 'Enter a latitude from -90 to 90.')
        elif abs(float(lon)) > 180:
            self.add_error('lon', 'Enter a longitude from -180 to 180.')
        elif {'lat', 'lon'} & set(self.changed_data) and not cleaned_data.get('point_is_right'):
            problem = self.point_problem(lat, lon)
            if problem:
                self.fields['point_is_right'].widget = forms.CheckboxInput()
                self.add_error('point_is_right', problem)

    def point_problem(self, lat, lon):
        """What to check about a point outside the team's usual area; None for a point inside it."""
        preferences = global_preferences_registry.manager()
        south, north, west, east = (preferences['general__event_area_' + edge]
                                    for edge in ('south', 'north', 'west', 'east'))

        def inside(lat, lon):
            return south <= float(lat) <= north and west <= float(lon) <= east

        if inside(lat, lon):
            return None
        for fixed in ((lat, flip_sign(lon)), (flip_sign(lat), lon), (flip_sign(lat), flip_sign(lon))):
            if inside(*fixed):
                return ('Did you mean {}, {}? The point as typed is outside the area the team '
                        'usually works in.'.format(*fixed))
        return 'This point is outside the area the team usually works in. Check it on a map.'


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
        members = (Member.members.filter(status__in=Member.CURRENT_MEMBERS)
                   .exclude(participant__period=period_id))
        return members

    def get_success_url(self):
        return self.object.period.event.get_absolute_url()

    def get_initial(self):
        period = get_object_or_404(Period, pk=self.kwargs.get('period'))
        return {
            'period':period,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pid = self.kwargs.get('period')
        period = Period.objects.filter(id=pid)[0]
        context['title'] = str(period)
        context['period_id'] = pid
        context['period_position'] = period.position
        context['event_id'] = period.event.id
        return context
