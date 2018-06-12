from django import forms
from .models import Message

class MessageCreateForm(forms.ModelForm):
    email = forms.BooleanField()
    phone = forms.BooleanField()

    class Meta:
        model = Message
        fields = ['author', 'text', 'format', 'period', 'period_format']
