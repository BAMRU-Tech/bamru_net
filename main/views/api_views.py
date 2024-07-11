from main.lib.gcal import get_gcal_manager
from main.models import *
from main.serializers import *

from django import forms
from django.db.models import Prefetch
from rest_framework import exceptions, generics, mixins, parsers, permissions, response, views, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django_filters import rest_framework as filters

import jinja2

class BaseViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.DjangoObjectPermissions,)

# From https://stackoverflow.com/a/40253309
class CreateListModelMixin(object):
    def get_serializer(self, *args, **kwargs):
        """ if an array is passed, set serializer to many """
        if isinstance(kwargs.get('data', {}), list):
            kwargs['many'] = True
        return super(CreateListModelMixin, self).get_serializer(*args, **kwargs)


class MemberViewSet(BaseViewSet):
    queryset = Member.annotate_unavailable(Member.objects).all().prefetch_related(
        'email_set',
        'phone_set',
        'role_set',
    )
    serializer_class = MemberSerializer
    filterset_fields = ('status', )
    search_fields = ('username',  )


class UnavailableFilter(filters.FilterSet):
    start_on = filters.DateFromToRangeFilter()
    class Meta:
        model = Unavailable
        fields = ('member__status', 'start_on', )


class ApiUnavailableViewSet(BaseViewSet):
    queryset = Unavailable.objects.all()
    serializer_class = BareUnavailableSerializer
    filterset_class = UnavailableFilter
    search_fields = ('member__username', )


class MemberUnavailableViewSet(BaseViewSet):
    serializer_class = MemberUnavailableSerializer
    filterset_fields = ('status', )
    search_fields = ('username',  )

    def get_queryset(self):
        filter_kwargs = {}
        if hasattr(self.request, 'query_params'):
            if self.request.query_params.get('date_range_start'):
                filter_kwargs['end_on__gte'] = forms.DateField().clean(
                        self.request.query_params['date_range_start'])
            if self.request.query_params.get('date_range_end'):
                filter_kwargs['start_on__lte'] = forms.DateField().clean(
                        self.request.query_params['date_range_end'])
        return Member.members.all().prefetch_related(
            'role_set',
            Prefetch('unavailable_set', queryset=Unavailable.objects.filter(**filter_kwargs), to_attr='filtered_unavailable_set'),
        )


class CertViewSet(BaseViewSet):
    queryset = Cert.objects.select_related('subtype__type')
    serializer_class = CertSerializer
    filterset_fields = ('member', 'member__status', 'subtype__type', 'subtype')
    search_fields = ('member__username',  )


def is_valid(cert_list):
    for cert in cert_list:
        if not cert.is_expired:
            return True
    return False

def is_valid_subtype_in(value, cert_list):
    for cert in cert_list:
        if cert.subtype.name == value and not cert.is_expired:
            return True
    return False

class MemberCertFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Member.TYPES)
    class Meta:
        model = Member
        fields = ('status', )

class MemberCertViewSet(BaseViewSet):
    queryset = Member.objects.prefetch_related('cert_set__subtype__type', 'role_set')
    serializer_class = MemberCertSerializer
    filterset_class = MemberCertFilter
    search_fields = ('username',  )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        env = jinja2.Environment(autoescape=False)
        env.tests["valid"] = is_valid
        env.tests["valid_subtype_in"] = is_valid_subtype_in
        context.update({
            'env': env,
            'display_cert_types': CertType.display_cert_types,
        })
        return context

class EventFilter(filters.FilterSet):
    start_at = filters.DateFromToRangeFilter()
    finish_at = filters.DateFromToRangeFilter()
    class Meta:
        model = Event
        fields = ('type', 'start_at', 'finish_at', 'published',)


class EventViewSet(BaseViewSet):
    def get_queryset(self):
        qs = Event.objects.all().order_by('-start_at')
        if getattr(self, 'action', None) != 'list':
            # fetch data used by EventDetailSerializer
            qs = qs.prefetch_related(
                "period_set",
                "period_set__participant_set",
                "period_set__participant_set__member",
                "period_set__participant_set__member__phone_set",
                "period_set__participant_set__member__email_set",
                "period_set__participant_set__member__role_set",
            )
        return qs

    filterset_class = EventFilter
    search_fields = ('title', 'description', 'location', )

    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return EventListSerializer
        return EventDetailSerializer

    def perform_create(self, serializer):
        super(EventViewSet, self).perform_create(serializer)
        get_gcal_manager().sync_event(serializer.instance)

    def perform_update(self, serializer):
        super(EventViewSet, self).perform_update(serializer)
        get_gcal_manager().sync_event(serializer.instance)

    def perform_destroy(self, event):
        get_gcal_manager().delete_for_event(event)
        super(EventViewSet, self).perform_destroy(event)


class PeriodViewSet(BaseViewSet):
    queryset = Period.objects.prefetch_related(
        "participant_set",
        "participant_set__member",
        "participant_set__member__phone_set",
        "participant_set__member__email_set",
        "participant_set__member__role_set",
    ).all()
    serializer_class = PeriodSerializer


class ParticipantViewSet(CreateListModelMixin, BaseViewSet):
    queryset = Participant.objects.all()
    serializer_class = PeriodParticipantSerializer


class DoViewSet(BaseViewSet):
    queryset = DoAvailable.objects.all().order_by('week')
    serializer_class = DoSerializer
    filterset_fields = ('year', 'quarter', 'week', 'available', 'assigned',
                     'comment', 'member', )
    search_fields = ('member__username',)

    def list(self, request, *args, **kwargs):
        id = request.query_params.get('member', None)
        if id is not None:
            try:
                member = Member.objects.filter(id=id)[0]
            except:
                content = {'Bad param': 'Invalid member id'}
                return Response(content, status=status.HTTP_404_NOT_FOUND)
        else:
            member = None

        year = request.query_params.get('year', None)
        if year is not None:
            try:
                year = int(year)
                if year < 2010 or year > 2030:
                    raise
            except:
                content = {'Bad param': 'Invalid year'}
                return Response(content, status=status.HTTP_404_NOT_FOUND)

        quarter = request.query_params.get('quarter', None)
        if quarter is not None:
            try:
                quarter = int(quarter)
                if quarter < 1 or quarter > 4:
                    raise
            except:
                content = {'Bad param': 'Invalid quarter'}
                return Response(content, status=status.HTTP_404_NOT_FOUND)

        # If the request is a member and a specific quarter,
        # create all the objects for that quarter
        #import pdb; pdb.set_trace()
        if member is not None and year is not None and quarter is not None:
            for week in DoAvailable.weeks(year, quarter):
                availability, created = DoAvailable.objects.get_or_create(
                    member=member, year=year, quarter=quarter, week=week)
                if created:
                    availability.save()

        return super(DoViewSet, self).list(self, request, *args, **kwargs)


class MessageFilter(filters.FilterSet):
    created_at = filters.DateFromToRangeFilter()
    class Meta:
        model = Message
        fields = ('created_at', )


class MessageViewSet(BaseViewSet):
    queryset = Message.objects.all().prefetch_related(
        'author',
        'author__email_set',
        'author__phone_set',
        'author__role_set',
        'rsvp_template',
    )
    filterset_class = MessageFilter
    search_fields = ('author__username',)
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return MessageListSerializer
        return MessageDetailSerializer


class InboundSmsViewSet(BaseViewSet):
    queryset = InboundSms.objects.all()
    serializer_class = InboundSmsSerializer
    filterset_fields = ('member', 'outbound', 'outbound__distribution__message__period')
    search_fields = ('member__username', )


class MemberPhotoViewSet(BaseViewSet):
    queryset = MemberPhoto.objects.all()
    serializer_class = MemberPhotoSerializer
    filterset_fields = ('member', )
    search_fields = ('member__username', )
