from main.models import *
from main.serializers import *

from rest_framework import generics, permissions, viewsets
from django_filters import rest_framework as filters

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
    permission_classes = (permissions.IsAuthenticated),
    filterset_class = UnavailableFilter
    search_fields = ('member__username',  )


class CertViewSet(viewsets.ModelViewSet):
    queryset = Cert.objects.all()
    serializer_class = CertSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('member__member_rank', 'type', )
    search_fields = ('member__username',  )


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
