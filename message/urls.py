from django.urls import path
from django.conf.urls import include, url

from . import views

app_name = 'message'
urlpatterns = [

    path('message/<int:pk>/', views.MessageDetailView.as_view(),
         name='message_detail'),
    path('message/add/',
         views.MessageCreateView.as_view(),
         name='message_add'),

    path('unauth_rsvp/<slug:token>/', views.unauth_rsvp, name='unauth_rsvp'),


    # TODO: move this to webhooks/, also updating mailgun and twilio
    url(r'^bnet/anymail/', include('anymail.urls')),
    path('bnet/sms_callback/', views.sms_callback, name='sms_callback'),
    url(r'^bnet/sms/$', views.sms),
    url(r'^bnet/test_send/$', views.test_send),
]
