from django.urls import path
from django.conf.urls import include, url

from . import views

app_name = 'bnet'
urlpatterns = [
    path('member/', views.MemberIndexView.as_view(), name='member_index'),
    path('member/<int:pk>/', views.MemberDetailView.as_view(), name='member_detail'),

    path('event/', views.EventIndexView.as_view(), name='event_index'),
    path('event/<int:pk>/', views.EventDetailView.as_view(), name='event_detail'),

    url(r'^anymail/', include('anymail.urls')),
    path('sms_callback/', views.sms_callback, name='sms_callback'),
    url(r'^sms/$', views.sms),
    url(r'^test_send/$', views.test_send),
]
