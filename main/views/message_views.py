import logging
from datetime import datetime, timedelta

from anymail.message import AnymailMessage
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
from django.views.decorators.csrf import csrf_exempt
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from dynamic_preferences.registries import global_preferences_registry
from twilio.twiml.messaging_response import MessagingResponse

from main.models import Member, Participant, Period

from main.models import (Distribution, InboundSms, Message, OutboundEmail,
                         OutboundSms, RsvpTemplate)
from main.views.member_views import MemberStatusTypeMixin

logger = logging.getLogger(__name__)


class MessageCreateBaseView(LoginRequiredMixin, MemberStatusTypeMixin, generic.ListView):
    model = Message
    template_name = 'message_add.html'
    context_object_name = 'member_list'
    page_format = None  # to override in urls

    def get_queryset(self):
        """Return context for standard paging."""
        format_convert = {'headsUp': ['invite', 'Heads Up'],
                          'available': ['invite', 'Available?'],
                          'leave': ['leave', 'Left?'],
                          'return': ['return', 'Returned?'],
                          'info': ['info', None],
                          'broadcast': ['broadcast', None],
                          'test': ['test', 'Test']
                          }
        initial = {}
        initial['author'] = self.request.user.pk
        initial['type'] = "std_page"
        initial['format'] = 'page'
        members = None
        page_format = self.request.GET.get('page_format', self.page_format)
        period_format = format_convert[page_format][0]
        initial['period_format'] = period_format
        rsvp_name = format_convert[page_format][1]
        self.rsvp_template = None
        if rsvp_name is not None:
            try:
                self.rsvp_template = RsvpTemplate.objects.get(name=rsvp_name)
                initial['rsvp_template'] = self.rsvp_template
            except RsvpTemplate.DoesNotExist:
                logger.error('RsvpTemplate {} not found for format: {}'.format(
                    rsvp_name, page_format))
        self.initial = initial
        return members

    def get_context_data(self, **kwargs):
        '''Add additional useful information.'''
        context = super().get_context_data(**kwargs)
        if self.rsvp_template and (self.initial['type'] != "repage"):
            self.initial['input'] = '{} {}'.format(self.initial['input'],
                                                   self.rsvp_template.text)
        instructions = {
            'invite': 'Page the team to invite them to the OP. Members already signed up still get a page.',
            'info': 'Send an informational page to people signed up for the OP. No response expected.',
            'broadcast': 'Send an informational page to the whole team. No response expected.',
            'leave': 'Transit page to people signed up for the event. Responses will mark the participant as departed.',
            'return': 'Transit page to people signed up for the event. Responses will mark the participant as returned home.',
            'test': 'Test page. DO NOT USE IN A REAL CALLOUT.',
        }
        self.initial['instructions'] = instructions.get(
            self.initial['period_format'], 'WARNING: Unknown period_format')
        return {**context, **self.initial}


class MessageTestCreateView(MessageCreateBaseView):
    page_format = 'test'
    def get_queryset(self):
        super().get_queryset()
        self.initial['type'] = "test"
        self.initial['input'] = datetime.now().strftime("Test page: %A, %d. %B %Y %I:%M%p")
        return Member.members.filter(id=self.request.user.pk)


class MessageRepageCreateView(MessageCreateBaseView):
    def get_queryset(self):
        message_id = self.kwargs['pk']
        message = None
        try:
            message = Message.objects.get(pk=message_id)
        except Message.DoesNotExist:
            logger.error('Message not found for: ' + message_id)
            raise Http404(
                'Message {} specified, but does not exist'.format(message_id))
        initial = {}
        initial['author'] = self.request.user.pk
        initial['type'] = "repage"
        if message.period is not None:
            initial['period_id'] = message.period.id
        initial['format'] = message.format
        initial['period_format'] = message.period_format
        initial['rsvp_template'] = message.rsvp_template
        self.rsvp_template = message.rsvp_template
        initial['input'] = 'Repage: ' + message.text
        initial['linked_rsvp_id'] = message.id
        if message.ancestry:
            initial['ancestry'] = '{}, {}'.format(
                message.ancestry, message_id)
        else:
            initial['ancestry'] = str(message_id)
        self.initial = initial
        members = []
        for d in message.distribution_set.filter(rsvp=False):
            if d.message.period_format == 'invite' and d.member.is_unavailable:
                logger.info('Repage of {} skipping unavailable member {}'.format(
                    message.id, d.member))
            else:
                members.append(d.member.id)
        return Member.objects.filter(id__in=members)


class MessageCreateView(MessageCreateBaseView):
    def get_queryset(self):
        super().get_queryset()
        period_id = self.request.GET.get('period')
        period_format = self.initial['period_format']
        members = None
        if period_id:
            try:
                period = Period.objects.get(pk=period_id)
            except Period.DoesNotExist:
                logger.error('Period not found for: ' + period_id)
                raise Http404(
                    'Period {} specified, but does not exist'.format(period_id))
            self.initial['period_id'] = period_id
            self.initial['period'] = str(period)

            if period_format == 'invite':
                # Invite all, even those who are already in the event (#443).
                # To exclude them add .exclude(participant__period=period_id)
                members = Member.members.filter(status__is_available=True)
            elif period_format == 'leave':
                members = period.members_for_left_page()
            elif period_format == 'return':
                members = period.members_for_returned_page()
            elif period_format == 'info':
                # Use .objects to allow info to guests
                members = Member.objects.filter(participant__period=period_id)
            elif period_format == 'broadcast':
                members = Member.members.filter(status__is_available=True)
            elif period_format == 'test':
                members = Member.members.filter(participant__period=period_id)
            else:
                logger.error('Period format {} not found for: {}'.format(
                period_format, self.request.body))
            if members is not None:
                members = Member.annotate_unavailable(members).prefetch_related(
                    'email_set',
                    'phone_set',
                    'role_set',
                )
            self.initial['input'] = "{}:".format(str(period))
        return members


class MessageDetailView(LoginRequiredMixin, generic.DetailView):
    model = Message
    template_name = 'message_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        message = self.object
        duration_minutes = [15, 30, 60]
        rsvp_durations = [0 for d in duration_minutes]
        sent = 0
        delivered = 0
        rsvp = 0
        rsvp_yes = 0
        rsvp_no = 0
        for d in message.distribution_set.all():
            sent += 1
            if d.rsvp:
                rsvp += 1
                if d.rsvp_answer:
                    rsvp_yes += 1
                else:
                    rsvp_no += 1
            this_delivered = False
            for m in d.outboundsms_set.all():
                this_delivered |= m.delivered
            for m in d.outboundemail_set.all():
                this_delivered |= m.delivered
            if this_delivered:
                delivered += 1
            for i, minutes in enumerate(duration_minutes):
                if d.response_seconds and d.response_seconds < minutes * 60:
                    rsvp_durations[i] += 1
        context['stats'] = "{} sent, {} delivered, {} RSVPed".format(
            sent, delivered, rsvp)
        context['rsvp'] = "{} yes, {} no, {} unresponded".format(
            rsvp_yes, rsvp_no, sent - rsvp_yes - rsvp_no)
        if sent > 0:
            context['response_times'] = ", ".join(
                ["{:0.0%} in {} min".format(rsvp_durations[i] / sent, m)
                 for i, m in enumerate(duration_minutes)])
        return context


class GenericMessageListView(generic.ListView):
    model = Message
    template_name = 'message_list.html'
    context_object_name = 'message_list'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'author',
            'period__event',
        )


class MessageListView(LoginRequiredMixin, GenericMessageListView):
    paginate_by = 15
    ordering = ['-created_at']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add column sort for datatable (zero origin)
        context['sortOrder'] = '2, "dsc"'
        return context

class InboundSmsListView(LoginRequiredMixin, generic.ListView):
    template_name = 'inbound_list.html'
    context_object_name = 'inbound_list'

    def get_queryset(self):
        qs = InboundSms.objects.all()
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=31))
        qs = qs.select_related(
            'member',
            'outbound__distribution__message',
        )
        return qs.order_by('-created_at')


class MessageInboxView(LoginRequiredMixin, GenericMessageListView):
    def get_queryset(self):
        """Return event list within the last year """
        qs = super().get_queryset().filter(created_at__gte=timezone.now() - timedelta(days=365))
        member_id = self.kwargs.get('member_id', None)
        if member_id:
            qs = qs.filter(distribution__member__id=member_id)
        return qs.order_by('-created_at')


class MessageEventView(LoginRequiredMixin, GenericMessageListView):
    def get_queryset(self):
        qs = super().get_queryset()
        event_id = self.kwargs.get('event_id', None)
        if event_id:
            qs = qs.filter(period__event__id=event_id)
        return qs.order_by('-created_at')


def handle_distribution_rsvp(request, distribution, rsvp=False):
    """Helper function to process a RSVP response.
    distribution -- A Distribution object
    rsvp -- boolean RSVP response
    """
    distribution.handle_rsvp(rsvp)

    # Mark the RSVP in ancestors too
    for a in distribution.message.associated_messages():
        try:
            d = a.distribution_set.get(member=distribution.member)
        except Distribution.DoesNotExist:
            logger.info('{} not in distribution {} (related to {})'.format(
                distribution.member, a, distribution))
        else:
            d.handle_rsvp(rsvp)

    if distribution.message.period_format == 'test':
        return 'Test message response received.'

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
        return 'RSVP no to {} recorded.'.format(distribution.message.period)

    p = Participant.objects.filter(**participant_filter).first()
    if p:
        response = None
        if distribution.message.period_format == 'leave':
            if distribution.rsvp_answer:
                p.en_route_at = timezone.now()
                p.save()
                response = 'Departure time recorded for {}.'
            else:
                p.en_route_at = None
                p.save()
                response = 'Departure time cleared for {}.'
        elif distribution.message.period_format == 'return':
            if distribution.rsvp_answer:
                p.return_home_at = timezone.now()
                p.save()
                response = 'Return time recorded for {}.'
            else:
                p.return_home_at = None
                p.save()
                response = 'Return time cleared for {}.'
        else:
            if distribution.rsvp_answer:
                response = 'Response yes to {} received.'
            else:
                response = 'Response no to {} received.'
        return response.format(distribution.message.period)

    logger.error('Participant not found for: ' + str(request.body))
    return ('Error: You were not found as a participant for {}.'
            .format(distribution.message.period))


# This view does not need login or CSRF protection due to the RSVP token.
@csrf_exempt
def unauth_rsvp(request, token, rsvp):
    d = get_object_or_404(Distribution, unauth_rsvp_token=token)
    if d.unauth_rsvp_expires_at < timezone.now():
        response_text = "Error: token expired. Check that you're responding to a recent page."
    elif request.method == 'POST':
        post_rsvp = request.POST.get('rsvp')
        if rsvp != post_rsvp:
            response_text = 'Error: RSVP mismatch {} != {}'.format(rsvp, post_rsvp)
            logger.error(response_text)
        else:
            rsvp_yes = post_rsvp[0].lower() == 'y'
            response_text = handle_distribution_rsvp(request, d, rsvp_yes)
    else:
        return render(request, "unauth_rsvp.html",
                      context={'distribution':d, 'rsvp':rsvp})
    logger.info('Sending HTTP response to {}: {}'.format(d.member, response_text))
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
    global_preferences = global_preferences_registry.manager()
    response = MessagingResponse()
    twilio_request = decompose(request)
    twilio_request_body = str(twilio_request.body).strip()
    try:
        sms = InboundSms.objects.create(sid=twilio_request.messagesid,
                                        from_number=twilio_request.from_,
                                        to_number=twilio_request.to,
                                        body=twilio_request_body)
        logger.info('Received SMS from {}: {}'.format(twilio_request.from_,
                                                      twilio_request_body))
    except:
        logger.error('Unable to save message: ' + str(request.body))
        response.message('BAMRU.net Error: unable to parse your message.')
        return response

    sms.process()
    if sms.extra_info or not sms.outbound:
        if sms.outbound:
            time_slug = sms.outbound.distribution.message.time_slug
        else:
            time_slug = timezone.now().date().isoformat()
        try:
            message = AnymailMessage(
                subject='BAMRU.net response [{}]'.format(time_slug),
                body='{}\nFrom: {} ({})'.format(
                    twilio_request_body, sms.member, twilio_request.from_),
                to=[global_preferences['google__do_group']],
                from_email=settings.MAILGUN_EMAIL_FROM,
            )
            message.send()
        except Exception as e:
            logger.error('Anymail error: {}'.format(e))

    if not sms.outbound:
        logger.info('No matching OutboundSms from: {} to: {} body: {}'.format(
            twilio_request.from_, twilio_request.to, twilio_request_body))
        response.message(
            'BAMRU.net Warning: response ignored. No RSVP question in the past 24 hours.')
        return response

    if not (sms.yes or sms.no):
        logger.info('Unable to parse y/n message {} from {}: {}'.format(
            sms.body, sms.member, twilio_request_body))
        response.message('Could not parse yes/no in your message. Start your message with y or n.')
        return response

    text = handle_distribution_rsvp(request, sms.outbound.distribution, sms.yes)
    logger.info('Sending SMS response to {}: {}'.format(sms.member, text))
    response.message(text)
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


class ActionBecomeDo(LoginRequiredMixin, MemberStatusTypeMixin, generic.ListView):
    model = Message
    template_name = 'message_add.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.members.filter(status__is_do_eligible=True).order_by('id')

    def get_context_data(self, **kwargs):
        """Return context for become DO"""
        context = super().get_context_data(**kwargs)

        # DO PII
        do = self.request.user
        context['title'] = "Page DO transition"

        context['format'] = 'do_shift_starting'
        context['period_format'] = 'broadcast'
        # text box canned message
        start = datetime.now()
        # set end to next Tuesday
        end = start + timedelta(7 - (start.weekday() - 1)  % 7)
        do_shift = "{} to {}".format(start.strftime("0800 %B %-d"),
                                     end.strftime("0800 %B %-d"))
        input = "BAMRU DO from {} is {} ({}, {})"
        context['input'] = input.format( do_shift, do.full_name,
                                         do.display_phone, do.display_email)
        context['confirm_prologue']  = "Correct data and time for your shift?\\n"
        context['type'] = "do_page"

        return context
