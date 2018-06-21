from django import forms
from .models import Message

class MessageCreateForm(forms.ModelForm):
    email = forms.BooleanField(required=False)
    phone = forms.BooleanField(required=False)

    class Meta:
        model = Message
        fields = ['author', 'text', 'format', 'period', 'period_format', 'rsvp_template']
