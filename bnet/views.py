from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.views import generic
from django_twilio.client import twilio_client
from django_twilio.decorators import twilio_view
from twilio.twiml.messaging_response import MessagingResponse

from .models import Member


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
def sms(request):
    r = Response()
    r.message('Hello from your Django app!')
    return r

def test_send(request):
    twilio_client.messages.create(
        body="test message",
        to="+18182747750",
        from_="415-599-2671",
        )
    return HttpResponse("Done")
    
