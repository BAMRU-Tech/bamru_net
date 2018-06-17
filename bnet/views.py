from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import generic
from django_twilio.client import twilio_client
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from twilio.twiml.messaging_response import MessagingResponse
from .forms import MessageCreateForm
from .models import Event, InboundSms, Member, OutboundSms, Participant, Period, Message

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


class MessageCreateView(LoginRequiredMixin, generic.edit.CreateView):
    model = Message
    form_class = MessageCreateForm
    template_name = 'base_form.html'

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_initial(self):
        initial = super(MessageCreateView, self).get_initial().copy()
        initial['author'] = self.request.user.pk
        if self.request.GET.get('period'):
            initial['format'] = 'page'
            initial['period'] = self.request.GET.get('period')
            initial['period_format'] = self.request.GET.get('period_format')
            try:
                initial['text'] = str(Period.objects.get(pk=initial['period']))
            except Period.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        message = form.instance
        message.save()
        if self.request.POST.get('period'):
            period = get_object_or_404(Period, pk=self.request.POST.get('period'))
            if self.request.GET.get('period_format') == 'invite':
                for m in Member.page_objects.all():
                    message.distribution_set.create(
                        member=m,
                        email=form.cleaned_data['email'],
                        phone=form.cleaned_data['phone'])
            else:
                for p in period.participant_set.all():
                    message.distribution_set.create(
                        member=p.member,
                        email=form.cleaned_data['email'],
                        phone=form.cleaned_data['phone'])
        message.send()
        return super().form_valid(form)


class MessageDetailView(LoginRequiredMixin, generic.DetailView):
    model = Message
    template_name = 'message_detail.html'


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
        logger.error('Unable to save message: ' + request.body)
        response.message('BAMRU.net Error: unable to parse your message.')
        return response

    date_from = timezone.now() - timedelta(hours=12)
    outbound = (OutboundSms.objects
                .filter(member_number=twilio_request.from_,
                        created_at__gte=date_from)
                .order_by('-pk').first())
    # TODO filter by texts that have associated question
    if not outbound:
        logger.error('No matching OutboundSms for: ' + request.body)
        response.message('BAMRU.net Warning: not sure what to do with your message. Maybe it was too long ago.')
        return response
        
    yn = twilio_request.body[0].lower()
    if yn != 'y' and yn != 'n':
        logger.error('Unable to parse y/n message: ' + request.body)
        response.message('Could not parse yes/no in your message.')
        return response
        
    d = outbound.distribution
    d.rsvp = True
    d.rsvp_answer = (yn == 'y')
    d.save()

    if not d.rsvp_answer:  # Answered no = nothing to do
        response.message('Response no to {} received.'.format(d.message.period))
        return response
    
    participant_filter = {'period':d.message.period,
                          'member':d.member}
    if d.message.period_format == 'invite':
        Participant.objects.get_or_create(**participant_filter)
        response.message('RSVP yes to {} successful.'.format(d.message.period))
        return response
        
    p = Participant.objects.filter(**participant_filter).first()
    if p:
        if d.message.period_format == 'leave':
            p.en_route_at = timezone.now()
            response.message('Departure time recorded for {}.'.format(d.message.period))
        elif d.message.period_format == 'return':
            p.return_home_at = timezone.now()
            response.message('Return time recorded for {}.'.format(d.message.period))
        else:
            response.message('Unknown response for {} page for {}.'
                             .format(d.message.period_format, d.message.period))
        p.save()
    else:
        response.message('Error: You were not found as a participant for {}.'
                         .format(d.message.period))
        logger.error('Participant not found for: ' + request.body)
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
