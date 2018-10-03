from .models import Cert, Event, Member, Participant, Period, Unavailable
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

        
class ParticipantSerializer(serializers.HyperlinkedModelSerializer):
    member = MemberSerializer()
    class Meta:
        model = Participant
        fields = ('id', 'member', 'ahc', 'ol')

        
class BareParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol')


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
