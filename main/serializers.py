from .models import *
from .tasks import message_send
from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import exceptions, serializers
from rest_framework.validators import UniqueTogetherValidator
from collections import defaultdict
from base64 import b64encode, b64decode

import logging
logger = logging.getLogger(__name__)

class WriteOnceMixin:
    """Supports Meta list: write_once_fields = ('a','b')"""
    def get_extra_kwargs(self):
        extra_kwargs = super().get_extra_kwargs()

        # Mark fields as read only on PUT/PATCH ('update')
        if 'update' in getattr(self.context.get('view'), 'action', ''):
            for field_name in getattr(self.Meta, 'write_once_fields', None):
                kwargs = extra_kwargs.get(field_name, {})
                kwargs['read_only'] = True
                extra_kwargs[field_name] = kwargs

        return extra_kwargs


class CreatePermModelSerializer(serializers.ModelSerializer):
    """Check object permissions on create."""
    def create(self, validated_data):
        obj = self.Meta.model(**validated_data)
        view = self._context['view']
        request = self._context['request']
        for permission in view.get_permissions():
            if not permission.has_object_permission(request, view, obj):
                raise exceptions.PermissionDenied
        return super(CreatePermModelSerializer, self).create(validated_data)


class MemberSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Member
        read_only_fields = ('username', 'full_name', 'status', 'status_order',
                            'roles', 'role_order',
                            'display_email', 'display_phone', 'short_name',
                            'is_unavailable', 'is_staff', 'is_superuser',)
        fields = ('id', 'dl', 'ham', 'v9', 'is_current_do',
                  'last_login',) + read_only_fields


class BareUnavailableSerializer(WriteOnceMixin, serializers.ModelSerializer):
    class Meta:
        model = Unavailable
        write_once_fields = ('member',)
        fields = ('id', 'member', 'start_on', 'end_on', 'comment', )


class MemberUnavailableSerializer(serializers.HyperlinkedModelSerializer):
    def __init__(self, *args, **kwargs):
        self._unavailable_filter_kwargs = kwargs.pop(
            'unavailable_filter_kwargs', {})
        super().__init__(*args, **kwargs)

    busy = serializers.SerializerMethodField()

    def get_busy(self, member):
        busy = member.unavailable_set.all()
        busy = busy.filter(**self._unavailable_filter_kwargs)
        return BareUnavailableSerializer(busy, context=self.context, many=True).data

    class Meta:
        model = Member
        read_only_fields = ('full_name', 'status', 'status_order', 'roles', 'role_order')
        fields = ('id', 'busy') + read_only_fields


class CertSerializer(WriteOnceMixin, CreatePermModelSerializer):
    class Meta:
        model = Cert
        read_only_fields = ('is_expired', 'color', 'display', 'cert_name',)
        write_once_fields = ('member', 'type', )
        fields = ('id', 'expires_on', 'description', 'comment', 'link',
                 ) + read_only_fields + write_once_fields


class MemberCertSerializer(serializers.HyperlinkedModelSerializer):
    certs = serializers.SerializerMethodField()

    def get_certs(self, member):
        ordered_certs = member.cert_set.all().order_by('-expires_on', '-id')
        grouped_certs = defaultdict(list)
        for c in ordered_certs:
            grouped_certs[c.type].append(
                CertSerializer(c, context=self.context).data)
        return [grouped_certs[t[0]] for t in Cert.TYPES]

    class Meta:
        model = Member
        read_only_fields = ('full_name', 'status', 'status_order')
        fields = ('id', 'certs') + read_only_fields


class DoSerializer(WriteOnceMixin, serializers.ModelSerializer):
    class Meta:
        model = DoAvailable
        read_only_fields = ('start', 'end')
        write_once_fields = ('id', 'year', 'quarter', 'week', 'member')
        fields = ('available', 'assigned', 'comment', ) + read_only_fields + write_once_fields
        validators = [
            UniqueTogetherValidator(
                queryset=DoAvailable.objects.all(),
                fields=('year', 'quarter', 'week', 'member')
            )
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # only the DO planner can assign shifts
        user = getattr(self._context.get('request'), 'user', None)
        if (user is None or
            not user.has_perm('main.change_assigned_for_doavailable')):
            self.fields.get('assigned').read_only = True


class BareParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at',
                  'return_home_at', 'signed_in_at', 'signed_out_at')


class ParticipantSerializer(serializers.HyperlinkedModelSerializer):
    member = MemberSerializer()

    class Meta:
        model = Participant
        fields = ('id', 'member', 'ahc', 'ol', 'en_route_at',
                  'return_home_at', 'signed_in_at', 'signed_out_at')


class PeriodSerializer(serializers.HyperlinkedModelSerializer):
    participant_set = ParticipantSerializer(many=True, read_only=True)

    class Meta:
        model = Period
        fields = ('id', 'position', 'start_at',
                  'finish_at', 'participant_set',)


class EventListSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Event
        fields = ('id', 'title', 'type', 'leaders', 'description', 'location',
                  'lat', 'lon', 'start_at', 'finish_at', 'all_day', 'published',)


class EventDetailSerializer(EventListSerializer):
    period_set = PeriodSerializer(many=True, read_only=True)

    class Meta(EventListSerializer.Meta):
        model = Event
        fields = EventListSerializer.Meta.fields + ('period_set',)


class PeriodParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = ('id', 'period', 'member', 'ahc', 'ol', 'en_route_at',
                  'return_home_at', 'signed_in_at', 'signed_out_at')
        validators = [
            UniqueTogetherValidator(
                queryset=Participant.objects.all(),
                fields=('period', 'member')
            )
        ]

    def save(self, **kwargs):
        was_ahc = self.instance is not None and self.instance.ahc
        instance = super().save(**kwargs)
        if instance.ahc and not was_ahc:
            instance.member.set_do(True)
        return instance


class DistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Distribution
        read_only_fields = ('message',)
        fields = ('id', 'message', 'member', 'send_email', 'send_sms',)


# This version currently requires a period. Future uses can change this.
class MessageListSerializer(serializers.ModelSerializer):
    rsvp_template = serializers.CharField(allow_null=True)

    class Meta:
        model = Message
        read_only_fields = ('author', 'created_at',)
        fields = ('id', 'author', 'text', 'format', 'period',
                  'period_format', 'rsvp_template', 'created_at', 'ancestry',)


class MessageDetailSerializer(MessageListSerializer):
    distribution_set = DistributionSerializer(many=True, required=False)

    class Meta(MessageListSerializer.Meta):
        model = Message
        fields = MessageListSerializer.Meta.fields + ('distribution_set',)

    def create(self, validated_data):
        logger.debug('MessageSerializer.create' + str(validated_data))
        ds_data = validated_data.pop('distribution_set')
        author = self.context['request'].user

        template_str = validated_data.pop('rsvp_template')
        rsvp_template = None
        if template_str:
            try:
                rsvp_template = RsvpTemplate.objects.get(name=template_str)
            except RsvpTemplate.DoesNotExist:
                logger.error('RsvpTemplate {} not found'.format(template_str))

        message = Message.objects.create(
            author=author,
            rsvp_template=rsvp_template,
            **validated_data)
        for distribution_data in ds_data:
            d = message.distribution_set.create(**distribution_data)
        logger.info('Calling message.queue {}'.format(message.pk))
        message.queue()
        logger.info('Calling message_send {}'.format(message.pk))
        message_send.delay(message.pk)
        logger.debug('MessageSerializer.create done')
        if message.format == 'do_shift_starting':
            message.author.set_do(True)
        return message


class InboundSmsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InboundSms
        read_only_fields = ('sid', 'from_number', 'to_number', 'body', 'member', 'outbound', 'yes', 'no', 'extra_info', )
        fields = read_only_fields


class MemberPhotoSerializer(WriteOnceMixin, CreatePermModelSerializer):
    class Meta:
        model = MemberPhoto
        read_only_fields = ('name', 'extension', 'size', 'content_type')
        write_once_fields = ('member', 'file')
        fields = ('id', 'url', 'file', 'member', 'position', 'created_at', 'updated_at', 'name', 'extension', 'size', 'content_type', 'original_url', 'medium_url', 'thumbnail_url', 'gallery_thumb_url')

    file = serializers.ImageField(write_only=True)

    original_url = serializers.SerializerMethodField()
    medium_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    gallery_thumb_url = serializers.SerializerMethodField()

    def get_original_url(self, obj): return self.get_photo_url(obj, 'original')
    def get_medium_url(self, obj): return self.get_photo_url(obj, 'medium')
    def get_thumbnail_url(self, obj): return self.get_photo_url(obj, 'thumbnail')
    def get_gallery_thumb_url(self, obj): return self.get_photo_url(obj, 'gallery_thumb')

    def get_photo_url(self, obj, format):
        url = reverse('member_photo_download', args=[obj.id, format])
        return self.context['request'].build_absolute_uri(url)

    def create(self, validated_data):
        validated_data['size'] = validated_data['file'].size
        validated_data['name'] = validated_data['file'].name
        if '.' in validated_data['file'].name:
            validated_data['extension'] = validated_data['file'].name.split('.')[-1]
        validated_data['content_type'] = validated_data['file'].content_type
        return super().create(validated_data)
