from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.forms.models import ModelForm, modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from django.views.decorators.http import require_POST
from django.forms.widgets import HiddenInput, Select, Widget, SelectDateWidget

from dynamic_preferences.registries import global_preferences_registry

from main.lib.county import county_text
from main.lib.gcal import get_gcal_manager
from main.lib.lat_lon import NotAPoint, area_warning, degrees_text, point_text, read_point, reading_note
from main.lib.sun import sun_times
from main.models import DoAvailable, Member, Event, Participant, Period
from main.models.event import every_username, leader_parts
from main.views.api_views import EventFilter
from main import tasks

from datetime import timedelta
import datetime

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
        event = context['event']
        if event.leaders is None:
            result = [{ 'name': 'TBD', 'id': 0 }]
        else:
            result = [{ 'name': text, 'id': member_id or 0 }
                      for text, member_id in leader_parts(event.leaders, every_username())]

        context['leaders'] = result
        if event.lat and event.lon:
            context['sun'] = sun_times(event.lat, event.lon, timezone.localtime(event.start_at).date())
        context['current_do'] = DoAvailable.current_scheduled_do()
        context['esb_spreadsheet_url'] = (
            global_preferences_registry.manager()['general__esb_spreadsheet_url'])
        try:
            context['county'] = county_text(float(event.lat), float(event.lon))
        except (TypeError, ValueError):             # no point, or a stored point that isn't numbers
            context['county'] = None
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


class EventForm(ModelForm):
    # One box for the event's point, read in any common form and saved as lat and lon.
    lat_lon = forms.CharField(
        required=False, label='Lat/Lon',
        help_text='Any form, such as decimal degrees, degrees and minutes, UTM or USNG.')

    class Meta:
        model = Event
        fields = ['title', 'description', 'description_private', 'type',
                  'location', 'location_private', 'lat_lon', 'leaders',
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
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.lat and self.instance.lon:
            self.initial['lat_lon'] = '{}, {}'.format(self.instance.lat, self.instance.lon)
        # An edit page opened before the box existed posts no box; it leaves the point as stored.
        if self.is_bound and 'lat_lon' not in self.data:
            self.fields['lat_lon'].disabled = True

    def clean_lat_lon(self):
        """The point as lat and lon text to store, or None for no point. A saved point the member
        left untouched is kept exactly as stored."""
        if 'lat_lon' not in self.changed_data:
            return None
        try:
            point = read_point(self.cleaned_data['lat_lon'])
        except NotAPoint as problem:
            raise forms.ValidationError(str(problem))
        self.point_warning = point and area_warning(point.lat, point.lon)
        return point and (degrees_text(point.lat), degrees_text(point.lon))

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_at')
        finish = cleaned_data.get('finish_at')
        if finish and finish < start:
            self.add_error('finish_at', 'Finish time must not be earlier than start time')
        return cleaned_data

    point_warning = None

    def save(self, commit=True):
        if 'lat_lon' in self.changed_data:
            self.instance.lat, self.instance.lon = self.cleaned_data['lat_lon'] or (None, None)
        return super().save(commit)


@login_required
@require_POST
def event_lat_lon(request):
    """The Lat/Lon box's text read as the event form reads it, so the form can show the point
    converted in place, and warn of one outside the team's usual area, before the member saves."""
    try:
        point = read_point(request.POST.get('text'))
    except NotAPoint as problem:
        return JsonResponse({'error': str(problem)})
    if not point:
        return JsonResponse({'value': ''})
    return JsonResponse({'value': point_text(point.lat, point.lon), 'note': reading_note(point),
                         'warning': area_warning(point.lat, point.lon)})


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

    def form_valid(self, form):
        if form.point_warning:
            messages.warning(self.request, 'Lat/Lon: ' + form.point_warning)
        return super().form_valid(form)

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

    def form_valid(self, form):
        if form.point_warning:
            messages.warning(self.request, 'Lat/Lon: ' + form.point_warning)
        return super().form_valid(form)

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
