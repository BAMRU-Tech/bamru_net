import django.contrib.auth.forms
from main.models import Email

class PasswordResetForm(django.contrib.auth.forms.PasswordResetForm):
    def get_users(self, email):
        emails = Email.objects.filter(address__iexact=email)
        users = [e.member for e in emails]
        return [u for u in users if u.is_active and u.has_usable_password()]
