from django.urls import path
from django.conf.urls import include, url

from . import views

app_name = 'bnet'
urlpatterns = [

    url(r'^anymail/', include('anymail.urls')),
    path('sms_callback/', views.sms_callback, name='sms_callback'),
    url(r'^sms/$', views.sms),
    url(r'^test_send/$', views.test_send),
]
