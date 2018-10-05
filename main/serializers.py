from .models import Cert, DoAvailable, Event, Member, Participant, Period, Unavailable
from rest_framework import serializers
from collections import defaultdict


class MemberSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Member
        read_only_fields = ('full_name', 'rank', 'rank_order', 'roles', 'role_order', 'display_email', 'display_phone', 'short_name',)
        fields = ('id', 'url', 'first_name', 'last_name', 'username', 'dl', 'ham', 'v9',  'is_active', 'is_staff', 'is_current_do', 'is_superuser', 'last_login',) + read_only_fields


class UnavailableSerializer(serializers.HyperlinkedModelSerializer):
    member = MemberSerializer()
    class Meta:
        model = Unavailable
        fields = ('id', 'url', 'member', 'start_on', 'end_on', 'comment', )


class BareUnavailableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unavailable
        fields = ('id', 'member', 'start_on', 'end_on', 'comment', )


class MemberUnavailableSerializer(serializers.HyperlinkedModelSerializer):
    def __init__(self, *args, **kwargs):
        self._unavailable_filter_kwargs = kwargs.pop('unavailable_filter_kwargs', {})
        super().__init__(*args, **kwargs)

    busy = serializers.SerializerMethodField()
    def get_busy(self, member):
        busy = member.unavailable_set.all()
        busy = busy.filter(**self._unavailable_filter_kwargs)
        return BareUnavailableSerializer(busy, context=self.context, many=True).data

    class Meta:
        model = Member
        read_only_fields = ('full_name', 'rank', 'rank_order')
        fields = ('id', 'url', 'busy') + read_only_fields


class CertSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Cert
        read_only_fields = ('is_expired',)
        fields = ('id', 'url', 'member_id', 'type', 'expiration', 'description', 'comment', 'link', ) + read_only_fields


class MemberCertSerializer(serializers.HyperlinkedModelSerializer):
    certs = serializers.SerializerMethodField()
    def get_certs(self, member):
        ordered_certs = member.cert_set.all().order_by('-expiration', '-id')
        grouped_certs = defaultdict(list)
        for c in ordered_certs:
            grouped_certs[c.type].append(CertSerializer(c, context=self.context).data)
        return [grouped_certs[t[0]] for t in Cert.TYPES]
    class Meta:
        model = Member
        read_only_fields = ('full_name', 'rank', 'rank_order')
        fields = ('id', 'url', 'certs') + read_only_fields


class DoSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = DoAvailable
        fields = ('id', 'year', 'quarter', 'week', 'available', 'assigned', 'member_id')

        
class BareParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at')


class ParticipantSerializer(serializers.HyperlinkedModelSerializer):
    member = MemberSerializer()
    class Meta:
        model = Participant
        fields = ('id', 'member', 'ahc', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at')

        
class BareParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at')


class PeriodSerializer(serializers.HyperlinkedModelSerializer):
    participant_set = ParticipantSerializer(many=True, read_only=True)
    class Meta:
        model = Period
        fields = ('id', 'position', 'start', 'finish', 'participant_set',)


class EventListSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Event
        read_only_fields = ('display_title', 'display_location', 'display_start',)
        fields = ('id', 'url', 'title', 'type', 'leaders', 'description', 'location', 'start', 'finish',) + read_only_fields


class EventDetailSerializer(EventListSerializer):
    period_set = PeriodSerializer(many=True, read_only=True)
    class Meta(EventListSerializer.Meta):
        model = Event
        fields = EventListSerializer.Meta.fields + ('period_set',)


class PeriodParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at')


#FIXME: This is here to get fullname without interfering with ParticipantAdd
class BaseMemberSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Member
        fields = ('id', 'full_name',)


class EditPeriodParticipantSerializer(serializers.ModelSerializer):
    member = BaseMemberSerializer()
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at', 'return_home_at', 'signed_in_at', 'signed_out_at')


