from django.urls import path
from django.conf.urls import url

from . import views

app_name = 'bnet'
urlpatterns = [
    path('member/', views.MemberIndexView.as_view(), name='index'),
    path('member/<int:pk>/', views.MemberDetailView.as_view(), name='detail'),
    url(r'^sms/$', views.sms),
    url(r'^test_send/$', views.test_send),
]
