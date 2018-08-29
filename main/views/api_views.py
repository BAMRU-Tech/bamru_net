from main.models import *
from main.serializers import *

from rest_framework import generics, permissions, viewsets

class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer
    permission_classes = (permissions.IsAuthenticated,)

class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-start')
    permission_classes = (permissions.IsAuthenticated,)
    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'list':
            return EventListSerializer
        return EventDetailSerializer
