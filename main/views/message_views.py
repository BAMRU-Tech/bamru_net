import logging
from datetime import datetime, timedelta

from anymail.signals import tracking
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.dispatch import receiver
from django.forms.widgets import HiddenInput, Select, SelectDateWidget, Widget
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views import generic
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from twilio.twiml.messaging_response import MessagingResponse

from main.models import Member, Participant, Period

from main.models import (Distribution, InboundSms, Message, OutboundEmail,
                         OutboundSms, RsvpTemplate)
from main.tasks import message_send

logger = logging.getLogger(__name__)


class MessageCreateView(LoginRequiredMixin, generic.ListView):
    model = Message
    template_name = 'message_add.html'
    context_object_name = 'member_list'

    #def get_success_url(self): FIXME
    #    return self.object.get_absolute_url()

    def get_queryset(self):
        """Return context for standard paging."""
        initial = {}
        initial['author'] = self.request.user.pk
        members = None
        period_id = self.request.GET.get('period')
        period_format = self.request.GET.get('period_format')
        page = self.request.GET.get('page')
        if period_id:
            try:
                period = Period.objects.get(pk=period_id)
            except Period.DoesNotExist:
                logger.error('Period not found for: ' + period_id)
                raise Http404(
                    'Period {} specified, but does not exist'.format(period_id))
            initial['format'] = 'page'
            initial['period_id'] = period_id
            initial['period_format'] = period_format
            initial['text'] = str(period)

            if period_format == 'invite':
                members = (Member.active
                .filter(member_rank__in=['TM','FM','T','R','S'])
                .exclude(participant__period=period_id))
            elif period_format == 'leave':
                members = period.members_for_left_page()
            elif period_format == 'return':
                members = period.members_for_returned_page()
            elif period_format == 'info':
                members = Member.active.filter(participant__period=period_id)
            elif period_format == 'broadcast':
                members = Member.active.filter(member_rank__in=['TM','FM','T','R','S'])
            elif period_format == 'test':
                members = period.members_for_test_page()
            else:
                logger.error('Period format {} not found for: {}'.format(
                period_format, self.request.body))

            rsvp_template = None
            try:
                rsvp_template = RsvpTemplate.objects.get(name=page)
                initial['rsvp_template'] = rsvp_template
            except RsvpTemplate.DoesNotExist:
                logger.error('RsvpTemplate {} not found for period: {}'.format(
                    page, period_id))

            self.initial = initial  # Is there a better way to get info into the template?

        initial['title'] = "Page"
        if (rsvp_template != None):  # TODO: add empty templates for Info and Broadcast
            initial['input'] = "{}: {}".format(str(period), rsvp_template.text)
        else:
            initial['input'] = "{}: ".format(str(period))
        initial['type'] = "std_page"

        return members

    def get_context_data(self, **kwargs):
        '''Add additional useful information.'''
        context = super().get_context_data(**kwargs)
        return {**context, **self.initial}


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


class MessageInboxView(LoginRequiredMixin, generic.ListView):
    template_name = 'message_list.html'
    context_object_name = 'message_list'

    def get_queryset(self):
        """Return event list within the last year """
        qs = Message.objects.all()
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=365))
        member_id = self.kwargs.get('member_id', None)
        if member_id:
            qs = qs.filter(distribution__member__id=member_id)
        return qs.order_by('-created_at')


def handle_distribution_rsvp(request, distribution, rsvp=False):
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

    logger.error('Participant not found for: ' + str(request.body))
    return ('Error: You were not found as a participant for {}.'
            .format(distribution.message.period))


def unauth_rsvp(request, token):
    d = get_object_or_404(Distribution, unauth_rsvp_token=token)
    if d.unauth_rsvp_expires_at < timezone.now():
        response_text = 'Error: token expired'
    else:
        rsvp = request.GET.get('rsvp')[0].lower() == 'y'
        response_text = handle_distribution_rsvp(request, d, rsvp)
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
        logger.error('Unable to save message: ' + str(request.body))
        response.message('BAMRU.net Error: unable to parse your message.')
        return response

    date_from = timezone.now() - timedelta(hours=12)
    outbound = (OutboundSms.objects
                .filter(destination=twilio_request.from_,
                        created_at__gte=date_from)
                .order_by('-pk').first())
    # TODO filter by texts that have associated question
    if (not outbound) or (not outbound.distribution):
        logger.error('No matching OutboundSms for: ' + str(request.body))
        response.message(
            'BAMRU.net Warning: not sure what to do with your message. Maybe it was too long ago.')
        return response

    yn = twilio_request.body[0].lower()
    if yn != 'y' and yn != 'n':
        logger.error('Unable to parse y/n message: ' + str(request.body))
        response.message('Could not parse yes/no in your message. Start your message with y or n.')
        return response

    response.message(handle_distribution_rsvp(
        request, outbound.distribution, (yn == 'y')))
    return response


@receiver(tracking)
def handle_outbound_email_tracking(sender, event, esp_name, **kwargs):
    logger.info('{}: {} ({})'.format(event.message_id,
                                     event.event_type, event.description))
    email = OutboundEmail.objects.get(sid=event.message_id)
    email.status = event.event_type
    email.error_message = event.description
    if email.error_message is None:
        email.error_message = ''
    if event.event_type == 'delivered':
        email.delivered = True
    if event.event_type == 'opened':
        email.opened = True
    email.save()


class ActionBecomeDo(LoginRequiredMixin, generic.ListView):
    model = Message
    template_name = 'message_add.html'
    context_object_name = 'member_list'

    #def get_success_url(self): FIXME
    #    return self.object.get_absolute_url()

    def get_queryset(self):
        """Return context with members to page."""
        initial = {}
        initial['author'] = self.request.user.pk
        members = None
        period_id = self.request.GET.get('period')
        period_format = self.request.GET.get('period_format')
        page = self.request.GET.get('page')

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.filter(
            member_rank__in=['TM','FM','T','R','S','A']).order_by('id')

    def get_context_data(self, **kwargs):
        """Return context for become DO"""
        context = super().get_context_data(**kwargs)

        context['type'] = "become_do"

        # DO PII
        do = self.request.user
        #context['do'] = do #FIXME: need?

        context['title'] = "Page DO transition"

        context['period_format'] = 'info'
        # text box canned message
        start = datetime.now()
        # set end to next Tuesday
        end = start + timedelta(7 - (start.weekday() - 1)  % 7)
        do_shift = "{} to {}".format(start.strftime("0800 %B %-d"),
                                     end.strftime("0800 %B %-d"))
        input = "BAMRU DO from {} is {} ({}, {})"
        context['input'] = input.format( do_shift, do.full_name,
                                         do.display_phone, do.display_email)
        context['text'] = 'TEXT'

        context['confirm_prologue']  = "Correct data and time for your shift?\\n"

        return context
