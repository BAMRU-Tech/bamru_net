from .models import Event, Member, Participant, Period
from rest_framework import serializers

class MemberSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Member
        read_only_fields = ('full_name', 'rank', 'display_email', 'display_phone', 'short_name',)
        fields = ('id', 'url', 'first_name', 'last_name', 'username', 'dl', 'ham', 'v9',  'is_active', 'is_staff', 'is_current_do', 'is_superuser', 'last_login',) + read_only_fields


class ParticipantSerializer(serializers.HyperlinkedModelSerializer):
    member = MemberSerializer()
    class Meta:
        model = Participant
        fields = ('id', 'member', 'ahc', 'ol')


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
