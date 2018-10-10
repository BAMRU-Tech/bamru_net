from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.forms import widgets
from django.forms.formsets import BaseFormSet
from django.forms.models import inlineformset_factory, modelform_factory, modelformset_factory
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, render_to_response
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import generic
from main.models import Address, Cert, Email, EmergencyContact,Member, Phone, Unavailable

from django.forms.widgets import HiddenInput, Select, Widget, SelectDateWidget

import datetime
from datetime import timedelta

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape


class MemberListView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.order_by('id')


class MemberDetailView(LoginRequiredMixin, generic.DetailView):
    model = Member
    template_name = 'member_detail.html'


class MemberEditView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'member_edit.html'

    MemberForm = modelform_factory(Member,
            fields=['first_name', 'last_name', 'ham', 'v9', 'dl'])
    PhonesForm = inlineformset_factory(Member, Phone,
            fields=['type', 'number', 'pagable', 'position'],
            widgets={
                'number': widgets.TextInput(attrs={'placeholder': 'Number'}),
                'position': widgets.HiddenInput(),
            },
            extra=0)
    EmailsForm = inlineformset_factory(Member, Email,
            fields=['type', 'address', 'pagable', 'position'],
            widgets={
                'address': widgets.TextInput(attrs={'placeholder': 'Email address'}),
                'position': widgets.HiddenInput(),
            },
            extra=0)
    AddressesForm = inlineformset_factory(Member, Address,
            fields=['type', 'address1', 'address2', 'city', 'state', 'zip', 'position'],
            widgets={
                'address1': widgets.TextInput(attrs={'placeholder': 'Address line 1'}),
                'address2': widgets.TextInput(attrs={'placeholder': 'Address line 2'}),
                'city': widgets.TextInput(attrs={'placeholder': 'City'}),
                'state': widgets.TextInput(attrs={'placeholder': 'State', 'size': 5}),
                'zip': widgets.TextInput(attrs={'placeholder': 'Zip', 'size': 5}),
                'position': widgets.HiddenInput(),
            },
            extra=0)
    ContactsForm = inlineformset_factory(Member, EmergencyContact,
            fields=['name', 'number', 'type', 'position'],
            widgets={
                'name': widgets.TextInput(attrs={'placeholder': 'Name'}),
                'number': widgets.TextInput(attrs={'placeholder': 'Number'}),
                'position': widgets.HiddenInput(),
            },
            extra=0)

    forms = None

    def get_forms(self, member):
        if self.forms is None:
            if self.request.method == 'POST':
                args = [self.request.POST]
            else:
                args = []
            forms = {}
            forms['member_edit'] = self.MemberForm(*args, prefix='member', instance=member)
            forms['phones_form'] = self.PhonesForm(*args, prefix='phones', instance=member)
            forms['emails_form'] = self.EmailsForm(*args, prefix='emails', instance=member)
            forms['addresses_form'] = self.AddressesForm(*args, prefix='addresses', instance=member)
            forms['contacts_form'] = self.ContactsForm(*args, prefix='contacts', instance=member)
            # Hack to prevent undesired behaivour on page refresh: Our
            # javascript modifies the value of TOTAL_FORMS when the user adds a
            # phone/email/etc. If the user then refreshes the page, the browser
            # remembers the incremented TOTAL_FORMS value and restores it. But
            # it does not restore the added form, so submitting results in
            # errors. Setting autocomplete off makes the browser leave
            # TOTAL_FORMS alone.
            for f in forms.values():
                if hasattr(f, 'management_form'):
                    f.management_form.fields['TOTAL_FORMS'].widget.attrs['autocomplete'] = 'off'
            self.forms = forms
        return self.forms

    def post(self, *args, **kwargs):
        if self.kwargs['pk'] != self.request.user.id:
            # TODO: more sophisticated permissions (e.g. allow secretary to edit).
            raise PermissionDenied

        member = Member.objects.get(id=self.kwargs['pk'])

        forms = self.get_forms(member)
        if not all([f.is_valid() for f in forms.values()]):
            return self.get(*args, **kwargs)
        for f in forms.values():
            f.save()

        return HttpResponseRedirect(reverse('member_detail', args=[member.id]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        member = Member.objects.get(id=self.kwargs['pk'])
        context['member'] = member
        context.update(self.get_forms(member))
        return context


class MemberCertListView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_cert_list.html'
    context_object_name = 'cert_list'

    def get_queryset(self):
        qs = Cert.objects.filter(member=self.kwargs['pk'])
        qs = qs.order_by(Cert.type_order_expression(), '-expiration', '-id')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = Member.objects.filter(id=self.kwargs['pk']).first()
        context['cert_types'] = Cert.TYPES
        return context


class CertEditMixin:
    model = Cert
    template_name = 'cert_form.html'

    def get_cert_type(self):
        # subclasses must implement
        raise Exception

    def get_form_class(self):
        cert_type = self.get_cert_type()

        fields = ['id', 'type', 'expiration', 'description']
        if cert_type == "ham":
            fields += ['link']
        else:
            fields += [
                # TODO: file upload
                'comment',
            ]
        return modelform_factory(
            Cert,
            fields=fields,
            widgets={
                'id': widgets.HiddenInput(),
                'type': widgets.HiddenInput(),
                'description': widgets.TextInput(),
                'comment': widgets.TextInput(),
                'link': widgets.TextInput(),
                'expiration': widgets.DateInput(attrs={'type': 'date'}),
            },
        )

    def get_initial(self):
        return {'type': self.get_cert_type()}

    def form_valid(self, form):
        if self.kwargs['member'] != self.request.user.id:
            # TODO: more sophisticated permissions (e.g. allow secretary to edit).
            raise PermissionDenied

        cert = form.save(commit=False)

        if cert.member_id and cert.member_id != self.request.user.id:
            # TODO: more sophisticated permissions (e.g. allow secretary to edit).
            raise PermissionDenied

        cert.member = self.request.user
        cert.save()
        return HttpResponseRedirect(reverse('member_cert_list', args=[cert.member.id]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = Member.objects.get(id=self.kwargs['member'])
        return context


class CertCreateView(LoginRequiredMixin, CertEditMixin, generic.edit.CreateView):
    def get_cert_type(self):
        if self.request.method == 'POST':
            return self.request.POST['type']
        else:
            return self.request.GET.get('type', 'medical')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['new'] = True
        context['cert'] = Cert(type=self.get_cert_type())
        return context


class CertDeleteView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'cert_delete.html'

    def post(self, *args, **kwargs):
        if self.kwargs['member'] != self.request.user.id:
            # TODO: more sophisticated permissions (e.g. allow secretary to edit).
            raise PermissionDenied

        cert = Cert.objects.get(id=self.kwargs['cert'])
        member_id = cert.member.id

        if self.kwargs['member'] != cert.member.id:
            return HttpResponseBadRequest()

        cert.delete()
        return HttpResponseRedirect(reverse('member_certs', args=[member_id]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cert = Cert.objects.get(id=self.kwargs['cert'])
        context['cert'] = cert
        context['member'] = cert.member
        return context


class CertListView(LoginRequiredMixin, generic.ListView):
    template_name = 'cert_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        # 0 = cert
        # 1 = count
        cert_lookup = {}
        for idx, t in enumerate(Cert.TYPES):
            cert_lookup[t[0]] = idx
        qs = Member.members.prefetch_related('cert_set')
        for m in qs:
            m.certs = [{'cert':None, 'count':0} for x in cert_lookup]
            #m.cert_count = cert_count.copy()
            for c in m.cert_set.all():
                idx = cert_lookup[c.type]
                prev = m.certs[idx]['cert']
                # Choose when to replace the existing one in the list
                if ((not prev) or
                    (not prev.position) or
                    ((prev.position > c.position) and
                     (prev.is_expired or not c.is_expired)) or
                    (prev.is_expired and not c.is_expired)
                ):
                    m.certs[idx]['cert'] = c
                m.certs[idx]['count'] += 1
                #m.cert_count[idx] += 1
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['headers'] = [x[1] for x in Cert.TYPES]
        return context


class AvailableListView(LoginRequiredMixin, generic.ListView):
    template_name = 'available_list.html'
    context_object_name = 'member_list'

    # TODO split this into a Mixin shared with DoAbstractView and API
    def get_date_param(self, name):
        today = timezone.now().today().date()
        val = self.request.GET.get(name, '')
        setattr(self, name, int(val) if val.isnumeric() else getattr(today,name))

    def get_params(self):
        self.get_date_param('year')
        self.get_date_param('month')
        self.get_date_param('day')
        self.days = int(self.request.GET.get('days', 5))
        self.date = datetime.date(self.year, self.month, self.day)

    def get_queryset(self):
        self.get_params()
        today = self.date
        unavailable_set = Unavailable.objects.filter(
            end_on__gte=today).order_by('start_on')
        qs = Member.objects.prefetch_related(
            Prefetch('unavailable_set',
                     queryset=unavailable_set,
                     to_attr='unavailable_filtered')
        ).order_by('id')
        for m in qs:
            m.days = ['' for x in range(self.days)]
            for u in m.unavailable_filtered:
                if u.start_on >= today + timedelta(days=self.days):
                    continue  # not in date range
                if u.start_on <= today:
                    start = 0
                else:
                    start = (u.start_on - today).days

                end = (u.end_on - today).days + 1
                if end > self.days:
                    end = self.days
                    m.end_date = u.end_on

                comment = u.comment
                if not comment:
                    comment = 'BUSY'
                for day in range(start, end):
                    m.days[day] = comment
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['days'] = self.days
        context['headers'] = [self.date + timedelta(days=d)
                              for d in range(self.days)]
        return context

class MemberAvailabilityListView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_availability_list.html'
    context_object_name = 'availability_list'

    def get_queryset(self):
        """Return the availability list."""
        qs = Unavailable.objects.filter(member=self.request.user)
        return Unavailable.objects.filter(member=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = Member.objects.filter(id=self.kwargs['pk']).first()
        return context
