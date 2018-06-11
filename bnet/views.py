from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import generic
from django_twilio.client import twilio_client
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from twilio.twiml.messaging_response import MessagingResponse
from .models import Event, InboundSms, Member, OutboundSms, Participant, Period

from datetime import datetime, timedelta

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape

class OrderListJson(BaseDatatableView):
    # The model we're going to show
    model = Member

    # define the columns that will be returned
    columns = ['last_name', 'typ', 'role', 'phone', 'email']
        
    # define column names that will be used in sorting
    # order is important and should be same as order of columns
    # displayed by datatables. For non sortable columns use empty
    # value like ''
    order_columns = ['last_name', 'typ', 'role', '', '']

    # set max limit of records returned, this is used to protect our site if someone tries to attack our site
    # and make it return huge amount of data
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
    fields = ['title', 'leaders', 'description', 'location', 'start', 'finish',
              ]
    template_name = 'base_form.html'


class EventCreateView(LoginRequiredMixin, generic.edit.CreateView): # In Progres #}
    model = Event
    fields = ['title', 'leaders', 'description', 'location', 'start', 'finish',]


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


@twilio_view
def sms_callback(request):
    logger.info(request.body)
    twilio_request = decompose(request)
    sms = OutboundSms.objects.get(sid=twilio_request.messagesid)
    sms.status = twilio_request.messagestatus
    if hasattr(twilio_request, 'errorcode'):
        sms.error_code = twilio_request.errorcode
    sms.save()
    return HttpResponse('')


@twilio_view
def sms(request):
    logger.info(request.body)
    response = MessagingResponse()
    twilio_request = decompose(request)
    try:
        sms = InboundSms.objects.create(sid=twilio_request.messagesid,
                                        from_number=twilio_request.from_,
                                        to_number=twilio_request.to,
                                        body=twilio_request.body)
    except:
        logger.error("Unable to save message: " + request.body)
        response.message('BAMRU.net Error: unable to parse your message.')
        return response

    response.message('BAMRU.net Warning: not sure what to do with your message.')
    return response


@login_required
def test_send(request):
    message = twilio_client.messages.create(
        body="test message",
        to="+18182747750",
        from_=settings.TWILIO_SMS_FROM,
        status_callback= 'http://{}{}'.format(settings.HOSTNAME, reverse('bnet:sms_callback')),
        )
    return HttpResponse('done ' + message.sid)
