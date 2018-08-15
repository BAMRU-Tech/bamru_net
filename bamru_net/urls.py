"""
    bamru_net URL Configuration

    The `urlpatterns` list routes URLs to views. For more information please see:
        https://docs.djangoproject.com/en/2.0/topics/http/urls/
    Examples:
    Function views
        1. Add an import:  from my_app import views
        2. Add a URL to urlpatterns:  path('', views.home, name='home')
    Class-based views
        1. Add an import:  from other_app.views import Home
        2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
    Including another URLconf
        1. Import the include() function: from django.urls import include, path
        2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf.urls import url
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from bnet import views

urlpatterns = [
    path('member/', views.MemberIndexView.as_view(), name='member_index'),
    path('member/<int:pk>/', views.MemberDetailView.as_view(), name='member_detail'),
    path('event/', views.EventIndexView.as_view(), name='event_index'),
    path('event/all', views.EventAllView.as_view(), name='event_all'),
    path('event/<int:pk>/', views.EventDetailView.as_view(), name='event_detail'),
    path('event/add', views.EventCreateView.as_view(), name='event_add'),
    path('event/<int:pk>/edit/', views.EventUpdateView.as_view(), name='event_update'),
    path('event/participant/add/<int:period>/',
         views.ParticipantCreateView.as_view(), name='event_participant_add'),
    path('event/<int:event>/participant/delete/<int:pk>/',
         views.ParticipantDeleteView.as_view(), name='event_participant_delete'),

    path('do/', views.DoListView.as_view(), name='do_index'),
    path('do/plan/', views.DoPlanView.as_view(), name='do_plan'),
    path('do/edit/', views.DoEditView.as_view(), name='do_form'),

    path('', include('message.urls')),

    path('admin/', admin.site.urls),

    url(r'^accounts/login/$', auth_views.login, name='login'),
    url(r'^accounts/logout/$', auth_views.logout, {'next_page': '/'}, name='logout'),
]
