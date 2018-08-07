import logging
from datetime import datetime, timedelta

from anymail.signals import tracking
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.dispatch import receiver
from django.forms.widgets import Select, SelectDateWidget, Widget
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views import generic
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from twilio.twiml.messaging_response import MessagingResponse

from bnet.models import Member, Participant, Period

from .forms import MessageCreateForm
from .models import (Distribution, InboundSms, Message, OutboundEmail,
                     OutboundSms, RsvpTemplate)
from .tasks import message_send

logger = logging.getLogger(__name__)


class MessageCreateView(LoginRequiredMixin, generic.edit.CreateView):
    model = Message
    template_name = 'base_form.html'

    def get_success_url(self):
        return self.object.get_absolute_url()

    def get_form(self, form_class=None):
        """Return an instance of the form to be used in this view."""
        kwargs = self.get_form_kwargs()
        initial = kwargs['initial']
        initial['author'] = self.request.user.pk
        members = None
        period_id = self.request.GET.get('period')
        period_format = self.request.GET.get('period_format')
        if period_id:
            try:
                period = Period.objects.get(pk=period_id)
            except Period.DoesNotExist:
                logger.error('Period not found for: ' + self.request.body)
                raise Http404(
                    'Period {} specified, but does not exist'.format(period_id))
            initial['format'] = 'page'
            initial['period'] = period_id
            initial['period_format'] = period_format
            initial['text'] = str(period)

            if period_format == 'invite':
                members = Member.page_objects.exclude(
                    participant__period=period_id)
                template_str = 'Available?'
            else:
                if period_format == 'leave':
                    template_str = 'Left?'
                    members = period.members_for_left_page()
                else:
                    template_str = 'Returned?'
                    members = period.members_for_returned_page()

            initial['members'] = [m.id for m in members]

            try:
                initial['rsvp_template'] = RsvpTemplate.objects.get(
                    name=template_str).id
            except RsvpTemplate.DoesNotExist:
                logger.error('RsvpTemplate {} not found for: {}'.format(
                    template_str, self.request.body))

        kwargs['initial'] = initial
        return MessageCreateForm(members, **kwargs)

    def form_valid(self, form):
        message = form.instance
        message.save()
        if self.request.POST.get('period'):
            period = get_object_or_404(
                Period, pk=self.request.POST.get('period'))
            for m in form.cleaned_data['members']:
                message.distribution_set.create(
                    member_id=m,
                    email=form.cleaned_data['email'],
                    phone=form.cleaned_data['phone'])
        logger.info('Calling message_send {}'.format(message.pk))
        message_send.delay(message.pk)
        return super().form_valid(form)


class MessageDetailView(LoginRequiredMixin, generic.DetailView):
    model = Message
    template_name = 'message_detail.html'


class MessageListView(LoginRequiredMixin, generic.ListView):
    template_name = 'message_list.html'
    context_object_name = 'message_list'

    def get_queryset(self):
        """Return event list within the last year """
        qs = Message.objects.all()
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=365))
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add column sort for datatable (zero origin)
        context['sortOrder'] = '2, "dsc"'
        return context


def handle_distribution_rsvp(distribution, rsvp=False):
    """Helper function to process a RSVP response.
    distribution -- A Distribution object
    rsvp -- boolean RSVP response
    """
    distribution.rsvp = True
    distribution.rsvp_answer = rsvp
    distribution.save()

    participant_filter = {'period': distribution.message.period,
                          'member': distribution.member}
    if distribution.message.period_format == 'invite':
        if distribution.rsvp_answer:
            Participant.objects.get_or_create(**participant_filter)
            return 'RSVP yes to {} successful.'.format(distribution.message.period)
        p = Participant.objects.filter(**participant_filter).first()
        if p:
            p.delete()
            return 'Canceled RSVP to {}.'.format(distribution.message.period)

    # Answered no to anything but invite = nothing to do
    if not distribution.rsvp_answer:
        return 'Response no to {} received.'.format(distribution.message.period)

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
        response_text = 'Error: token expired'
    else:
        rsvp = request.GET.get('rsvp')[0].lower() == 'y'
        response_text = handle_distribution_rsvp(d, rsvp)
    return HttpResponse(response_text)  # TODO template


@twilio_view
def sms_callback(request):
    twilio_request = decompose(request)
    sms = OutboundSms.objects.get(sid=twilio_request.messagesid)
    sms.status = twilio_request.messagestatus
    if sms.status == 'delivered':
        sms.delivered = True
    if hasattr(twilio_request, 'errorcode'):
        sms.error_code = twilio_request.errorcode
    sms.save()
    logger.info('sms_callback for {}: {}'.format(sms.sid, sms.status))
    return HttpResponse('')


@twilio_view
def sms(request):
    """Handle an incomming SMS message."""
    response = MessagingResponse()
    twilio_request = decompose(request)
    try:
        sms = InboundSms.objects.create(sid=twilio_request.messagesid,
                                        from_number=twilio_request.from_,
                                        to_number=twilio_request.to,
                                        body=twilio_request.body)
        logger.info('Received SMS from {}: {}'.format(twilio_request.from_,
                                                      twilio_request.body))
    except:
        logger.error('Unable to save message: ' + request.body)
        response.message('BAMRU.net Error: unable to parse your message.')
        return response

    date_from = timezone.now() - timedelta(hours=12)
    outbound = (OutboundSms.objects
                .filter(destination=twilio_request.from_,
                        created_at__gte=date_from)
                .order_by('-pk').first())
    # TODO filter by texts that have associated question
    if not outbound:
        logger.error('No matching OutboundSms for: ' + request.body)
        response.message(
            'BAMRU.net Warning: not sure what to do with your message. Maybe it was too long ago.')
        return response

    yn = twilio_request.body[0].lower()
    if yn != 'y' and yn != 'n':
        logger.error('Unable to parse y/n message: ' + request.body)
        response.message('Could not parse yes/no in your message.')
        return response

    response.message(handle_distribution_rsvp(
        outbound.distribution, (yn == 'y')))
    return response


@login_required
def test_send(request):
    from django_twilio.client import twilio_client
    message = twilio_client.messages.create(
        body="test message",
        to="+18182747750",
        from_=settings.TWILIO_SMS_FROM,
        status_callback='http://{}{}'.format(
            settings.HOSTNAME, reverse('message:sms_callback')),
    )
    return HttpResponse('done ' + message.sid)


@receiver(tracking)
def handle_outbound_email_tracking(sender, event, esp_name, **kwargs):
    logger.info('{}: {} ({})'.format(event.message_id,
                                     event.event_type, event.description))
    email = OutboundEmail.objects.get(sid=event.message_id)
    email.status = event.event_type
    email.error_message = event.description
    if event.event_type == 'delivered':
        email.delivered = True
    if event.event_type == 'opened':
        email.opened = True
    email.save()
