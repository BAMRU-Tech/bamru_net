from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import generic
from django_twilio.client import twilio_client
from django_twilio.decorators import twilio_view
from django_twilio.request import decompose
from twilio.twiml.messaging_response import MessagingResponse

import logging
logger = logging.getLogger(__name__)

from .models import InboundSms, Member, OutboundSms


class MemberIndexView(generic.ListView):
    template_name = 'member/index.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.order_by('id')


class MemberDetailView(generic.DetailView):
    model = Member
    template_name = 'member/detail.html'

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

def test_send(request):
    message = twilio_client.messages.create(
        body="test message",
        to="+18182747750",
        from_=settings.TWILIO_SMS_FROM,
        status_callback= 'http://{}{}'.format(settings.HOSTNAME, reverse('bnet:sms_callback')),
        )
    return HttpResponse('done ' + message.sid)
    
