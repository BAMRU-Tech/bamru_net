from django import forms

from .models import Message


class MessageCreateForm(forms.ModelForm):
    email = forms.BooleanField(initial=True, required=False)
    phone = forms.BooleanField(required=False)

    class Meta:
        model = Message
        fields = ['author', 'text', 'format',
                  'period', 'period_format', 'rsvp_template']

    def __init__(self, members, *args, **kwargs):
        super(MessageCreateForm, self).__init__(*args, **kwargs)
        self.fields['members'] = forms.MultipleChoiceField(
            choices=[(m.id, str(m)) for m in members]
        )
