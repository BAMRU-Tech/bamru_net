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
from bnet.models import Period, Participant
from .forms import MessageCreateForm
from .models import Distribution, InboundSms, OutboundSms, Message

from django.forms.widgets import Select, Widget, SelectDateWidget

from datetime import datetime, timedelta

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape

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


def handle_distribution_rsvp(distribution, rsvp=False):
    """Helper function to process a RSVP response.
    distribution -- A Distribution object
    rsvp -- boolean RSVP response
    """
    distribution.rsvp = True
    distribution.rsvp_answer = rsvp
    distribution.save()

    if not distribution.rsvp_answer:  # Answered no = nothing to do
        return 'Response no to {} received.'.format(distribution.message.period)

    participant_filter = {'period':distribution.message.period,
                          'member':distribution.member}
    if distribution.message.period_format == 'invite':
        Participant.objects.get_or_create(**participant_filter)
        return 'RSVP yes to {} successful.'.format(distribution.message.period)

    p = Participant.objects.filter(**participant_filter).first()
    if p:
        if distribution.message.period_format == 'leave':
            p.en_route_at = timezone.now()
            p.save()
            return 'Departure time recorded for {}.'.format(distribution.message.period)
        elif distribution.message.period_format == 'return':
            p.return_home_at = timezone.now()
            p.save()
            return 'Return time recorded for {}.'.format(distribution.message.period)
        else:
            return ('Unknown response for {} page for {}.'
                    .format(distribution.message.period_format, distribution.message.period))

    logger.error('Participant not found for: ' + request.body)
    return ('Error: You were not found as a participant for {}.'
            .format(distribution.message.period))


def unauth_rsvp(request, token):
    d = get_object_or_404(Distribution, unauth_rsvp_token=token)
    if d.unauth_rsvp_expires_at < timezone.now():
        response_text =  'Error: token expired'
    else:
        rsvp = request.GET.get('rsvp')[0].lower() == 'y'
        response_text = handle_distribution_rsvp(d, rsvp)
    return HttpResponse(response_text)  # TODO template


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
    """Handle an incomming SMS message."""
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
        
    response.message(handle_distribution_rsvp(outbound.distribution, (yn == 'y')))
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
