from main.models import *
from main.serializers import *

from rest_framework import generics, permissions, viewsets

class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('member_rank', )
    search_fields = ('username',  )

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-start')
    permission_classes = (permissions.IsAuthenticated,)
    filter_fields = ('type', 'location', )
    search_fields = ('title', 'description', 'location', )
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return EventListSerializer
        return EventDetailSerializer
