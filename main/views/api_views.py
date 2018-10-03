from main.models import *
from main.serializers import *

from rest_framework import generics, mixins, parsers, permissions, viewsets
from rest_framework.decorators import action
from django_filters import rest_framework as filters


# From https://stackoverflow.com/a/40253309
class CreateListModelMixin(object):
    def get_serializer(self, *args, **kwargs):
        """ if an array is passed, set serializer to many """
        if isinstance(kwargs.get('data', {}), list):
            kwargs['many'] = True
        return super(CreateListModelMixin, self).get_serializer(*args, **kwargs)


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('member_rank', )
    search_fields = ('username',  )


class UnavailableFilter(filters.FilterSet):
    start_on = filters.DateFromToRangeFilter()
    class Meta:
        model = Unavailable
        fields = ('member__member_rank', 'start_on', )


class UnavailableViewSet(viewsets.ModelViewSet):
    queryset = Unavailable.objects.all()
    serializer_class = UnavailableSerializer
    permission_classes = (permissions.IsAuthenticated)
    filterset_class = UnavailableFilter
    search_fields = ('member__username',  )


class CertViewSet(viewsets.ModelViewSet):
    queryset = Cert.objects.all()
    serializer_class = CertSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('member__member_rank', 'type', )
    search_fields = ('member__username',  )


class MemberCertViewSet(viewsets.ModelViewSet):
    queryset = Member.members.prefetch_related('cert_set')
    serializer_class = MemberCertSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('member_rank', )
    search_fields = ('username',  )


class EventFilter(filters.FilterSet):
    start = filters.DateFromToRangeFilter()
    class Meta:
        model = Event
        fields = ('type', 'start', )


class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-start')
    permission_classes = (permissions.IsAuthenticated,)
    filterset_class = EventFilter
    search_fields = ('title', 'description', 'location', )
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return EventListSerializer
        return EventDetailSerializer


class PeriodViewSet(viewsets.ModelViewSet):
    queryset = Period.objects.all()
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = PeriodSerializer


class ParticipantViewSet(CreateListModelMixin, viewsets.ModelViewSet):
    queryset = Participant.objects.all()
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = BareParticipantSerializer


class DoViewSet(viewsets.ModelViewSet):
    queryset = DoAvailable.objects.all()
    serializer_class = DoSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('year', 'quarter', 'week', 'available', 'assigned')
    search_fields = ('member__username',)
