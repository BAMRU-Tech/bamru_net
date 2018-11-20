from main.models import *
from main.serializers import *

from django import forms
from rest_framework import generics, mixins, parsers, permissions, response, views, viewsets
from rest_framework.decorators import action
from django_filters import rest_framework as filters


class BaseViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated,)

# From https://stackoverflow.com/a/40253309
class CreateListModelMixin(object):
    def get_serializer(self, *args, **kwargs):
        """ if an array is passed, set serializer to many """
        if isinstance(kwargs.get('data', {}), list):
            kwargs['many'] = True
        return super(CreateListModelMixin, self).get_serializer(*args, **kwargs)


class MemberViewSet(BaseViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    filter_fields = ('status', )
    search_fields = ('username',  )


class UnavailableFilter(filters.FilterSet):
    start_on = filters.DateFromToRangeFilter()
    class Meta:
        model = Unavailable
        fields = ('member__status', 'start_on', )


class UnavailableViewSet(BaseViewSet):
    queryset = Unavailable.objects.all()
    serializer_class = UnavailableSerializer
    filterset_class = UnavailableFilter
    search_fields = ('member__username', )


class ApiUnavailableViewSet(BaseViewSet):
    queryset = Unavailable.objects.all()
    serializer_class = BareUnavailableSerializer
    filterset_class = UnavailableFilter
    search_fields = ('member__username', )


class MemberUnavailableViewSet(BaseViewSet):
    queryset = Member.members.prefetch_related('unavailable_set')
    serializer_class = MemberUnavailableSerializer
    filter_fields = ('status', )
    search_fields = ('username',  )

    def get_serializer(self, *args, **kwargs):
        filter_kwargs = {}
        if hasattr(self.request, 'query_params'):
            if self.request.query_params.get('date_range_start'):
                filter_kwargs['end_on__gte'] = forms.DateField().clean(
                        self.request.query_params['date_range_start'])
            if self.request.query_params.get('date_range_end'):
                filter_kwargs['start_on__lte'] = forms.DateField().clean(
                        self.request.query_params['date_range_end'])
        return super().get_serializer(*args, unavailable_filter_kwargs=filter_kwargs, **kwargs)


class CertViewSet(BaseViewSet):
    queryset = Cert.objects.all()
    serializer_class = CertSerializer
    filter_fields = ('member__status', 'type', )
    search_fields = ('member__username',  )


class MemberCertViewSet(BaseViewSet):
    queryset = Member.members.prefetch_related('cert_set')
    serializer_class = MemberCertSerializer
    filter_fields = ('status', )
    search_fields = ('username',  )


class EventFilter(filters.FilterSet):
    start = filters.DateFromToRangeFilter()
    finish = filters.DateFromToRangeFilter()
    class Meta:
        model = Event
        fields = ('type', 'start', 'finish', 'published',)


class EventViewSet(BaseViewSet):
    queryset = Event.objects.all().order_by('-start')
    filterset_class = EventFilter
    search_fields = ('title', 'description', 'location', )

    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return EventListSerializer
        return EventDetailSerializer


class PeriodViewSet(BaseViewSet):
    queryset = Period.objects.all()
    serializer_class = PeriodSerializer


class ParticipantViewSet(CreateListModelMixin, BaseViewSet):
    queryset = Participant.objects.all()
    serializer_class = PeriodParticipantSerializer


class DoViewSet(BaseViewSet):
    queryset = DoAvailable.objects.all()
    serializer_class = DoSerializer
    filter_fields = ('year', 'quarter', 'week', 'available', 'assigned', 'comment', 'member', )
    search_fields = ('member__username',)


class MessageFilter(filters.FilterSet):
    created_at = filters.DateFromToRangeFilter()
    class Meta:
        model = Message
        fields = ('created_at', )


class MessageViewSet(BaseViewSet):
    queryset = Message.objects.all()
    filterset_class = MessageFilter
    search_fields = ('author__username',)
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return MessageListSerializer
        return MessageDetailSerializer
