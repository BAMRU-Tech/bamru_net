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
from main import views

from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'events', views.EventViewSet)
router.register(r'periods', views.PeriodViewSet)
router.register(r'participants', views.ParticipantViewSet)
router.register(r'members', views.MemberViewSet)
router.register(r'member_certs', views.MemberCertViewSet, base_name='member')
router.register(r'certs', views.CertViewSet)
router.register(r'availability', views.UnavailableViewSet)

urlpatterns = [
    path('', views.IndexView.as_view()),
    path('member/', views.MemberIndexView.as_view(), name='member_index'),
    path('member/<int:pk>/', views.MemberDetailView.as_view(), name='member_detail'),
    path('member/<int:pk>/edit', views.MemberEditView.as_view(), name='member_edit'),
    path('member/<int:pk>/certs/', views.MemberCertsView.as_view(), name='member_certs'),
    path('member/<int:member>/certs/new', views.CertEditView.as_view(), name='new_cert', kwargs={'cert': 'new'}),
    path('member/<int:member>/certs/<int:cert>', views.CertEditView.as_view(), name='edit_cert'),
    path('member/<int:member>/certs/<int:cert>/delete', views.CertDeleteView.as_view(), name='delete_cert'),
    path('availability/', views.AvailableListView.as_view(), name='available_list'),
    path('availability/edit/', views.AvailableEditView.as_view(), name='available_edit'),

    path('event/proximate', views.EventImmediateView.as_view(), name='event_immediate'),
    path('event/', views.EventAllView.as_view(), name='event_all'),
    path('event/<int:pk>/', views.EventDetailView.as_view(), name='event_detail'),
    path('event/add', views.EventCreateView.as_view(), name='event_add'),
    path('event/<int:pk>/edit/', views.EventUpdateView.as_view(), name='event_update'),
    path('event/<int:pk>/delete/', views.EventDeleteView.as_view(), name='event_delete'),

    path('event/<int:pk>/period/add/',
         views.EventPeriodAddView.as_view(), name='event_period_add'),
    path('event/<int:event>/period/delete/<int:pk>/',
         views.EventPeriodDeleteView.as_view(), name='event_period_delete'),

    path('event/participant/add/<int:period>/',
         views.ParticipantCreateView.as_view(), name='event_participant_add'),
    path('event/<int:event>/participant/delete/<int:pk>/',
         views.ParticipantDeleteView.as_view(), name='event_participant_delete'),

    path('do/', views.DoListView.as_view(), name='do_index'),
    path('do/plan/', views.DoPlanView.as_view(), name='do_plan'),
    path('do/edit/', views.DoEditView.as_view(), name='do_form'),

    path('cert/', views.CertListView.as_view(), name='cert_list'),

    path('', include('message.urls')),

    url(r'^api/', include(router.urls)),
    url(r'^api-auth/', include('rest_framework.urls', namespace='rest_framework')),

    path('admin/', admin.site.urls),

    url(r'^accounts/login/$', auth_views.login, name='login'),
    url(r'^accounts/logout/$', auth_views.logout, {'next_page': '/'}, name='logout'),

    path('reports/', views.ReportIndexView.as_view(), name='reports_index'),
    path('reports/roster/BAMRU-roster.csv', views.ReportRosterCsvView.as_view()),
    path('reports/roster/BAMRU-roster.vcf', views.ReportRosterVcfView.as_view()),
    path('reports/roster/BAMRU-<str:roster_type>', views.ReportRosterView.as_view()),
]
