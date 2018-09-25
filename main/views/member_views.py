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

from datetime import timedelta
import datetime

import logging
logger = logging.getLogger(__name__)


from django_datatables_view.base_datatable_view import BaseDatatableView
from django.utils.html import escape


class MemberIndexView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_list.html'
    context_object_name = 'member_list'

    def get_queryset(self):
        """Return the member list."""
        return Member.objects.order_by('id')


class MemberDetailView(LoginRequiredMixin, generic.DetailView):
    model = Member
    template_name = 'member_detail.html'


class MemberEditView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'member_form.html'

    MemberForm = modelform_factory(Member,
            fields=['first_name', 'last_name', 'ham', 'v9', 'dl'])
    PhonesForm = inlineformset_factory(Member, Phone,
            fields=['type', 'number', 'pagable', 'sms_email', 'position'],
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
            forms['member_form'] = self.MemberForm(*args, prefix='member', instance=member)
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
            raise PermissionDenied

        member = Member.objects.get(id=self.kwargs['pk'])

        forms = self.get_forms(member)
        if not all([f.is_valid() for f in forms.values()]):
            return self.get(*args, **kwargs)
        for f in forms.values():
            f.save()
            #if not (isinstance(f, BaseFormSet) and f.can_order):
            #    f.save()
            #else:
                # Apparently it's not very easy to use can_order with a
                # ModelFormSet. Or possibly I'm missing something.
                #print()
                #print("instances direct:")
                #_ = f.save(commit=False)
                #for obj in instances:
                #    print(obj)
                #    #obj.save()
                #print("ordered forms:")
                #for i, individual_form in enumerate(f.ordered_forms):
                #    obj = individual_form.save(commit=False)
                #    obj.position = i
                #    print(obj, individual_form.has_changed())
                #    #obj.save()
                #print("deleted:")
                #for obj in f.deleted_objects:
                #    print(obj)
                ##    obj.delete()

        return HttpResponseRedirect(reverse('member_detail', args=[member.id]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        member = Member.objects.get(id=self.kwargs['pk'])
        context['member'] = member
        context.update(self.get_forms(member))
        return context


class MemberCertsView(LoginRequiredMixin, generic.ListView):
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


class CertEditView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'cert_form.html'

    def post(self, *args, **kwargs):
        if self.kwargs['member'] != self.request.user.id:
            # TODO: more sophisticated permissions (e.g. allow secretary to edit).
            raise PermissionDenied

        CertForm = self.get_form_class(self.request.POST['type'])
        if self.kwargs['cert'] == 'new':
            form = CertForm(self.request.POST)
        else:
            existing_cert = Cert.objects.get(id=self.kwargs['cert'])
            if existing_cert.member.id != self.kwargs['member']:
                return HttpResponseBadRequest()
            form = CertForm(self.request.POST, instance=existing_cert)

        if form.is_valid():
            cert = form.save(commit=False)
            cert.member = self.request.user
            cert.save()
        return HttpResponseRedirect(reverse('member_certs', args=[cert.member.id]))

    def get_form_class(self, cert_type):
        fields = ['id', 'type', 'expiration', 'description']
        if cert_type == "ham":
            fields += ['link']
        else:
            fields += [
                # TODO: file upload
                'comment',
            ]
        CertForm = modelform_factory(
            Cert,
            fields=fields,
            widgets={
                'id': widgets.HiddenInput(),
                'type': widgets.HiddenInput(),
                'description': widgets.TextInput(),
                'comment': widgets.TextInput(),
                'link': widgets.TextInput(),
            },
        )
        return CertForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        new = self.kwargs['cert'] == 'new'

        if new:
            cert_type = self.request.GET.get('type', 'medical')
            cert = Cert(type=cert_type)
        else:
            cert = Cert.objects.get(id=self.kwargs['cert'])
            cert_type = cert.type

        CertForm = self.get_form_class(cert_type)
        form = CertForm(instance=cert)

        context['new'] = new
        context['cert'] = cert
        context['form'] = form
        context['member'] = Member.objects.get(id=self.kwargs['member'])
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


class UnavailableListView(LoginRequiredMixin, generic.ListView):
    template_name = 'unavailable_list.html'
    context_object_name = 'member_list'

    # TODO split this into a Mixin shared with DoAbstractView
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
            m.days = [('',1) for x in range(self.days)]
            for u in m.unavailable_filtered:
                if u.start_on >= today + timedelta(days=self.days):
                    continue  # starts off the screen
                if u.start_on <= today:
                    start = 0
                else:
                    start = (u.start_on - today).days

                # Add one to include the end day
                end_delta = (u.end_on - today).days + 1
                if end_delta > self.days:
                    end_delta = self.days
                    m.end_date = u.end_on

                comment = u.comment
                if not comment:
                    comment = 'BUSY'
                for day in range(start, end_delta):
                    m.days[day] = (comment, end_delta-start)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['days'] = self.days
        context['headers'] = [self.date + timedelta(days=d)
                              for d in range(self.days)]
        return context

class UnavailableEditView(LoginRequiredMixin, generic.base.TemplateView):
    template_name = 'unavailable_form.html'

    def post(self, *args, **kwargs):
        return self.get(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        UnavailableFormSet = modelformset_factory(
            Unavailable,
            fields=['start_on', 'end_on', 'comment',],
        )

        qs = Unavailable.objects.filter(member=self.request.user)

        if self.request.method == 'POST':
            formset = UnavailableFormSet(self.request.POST)
            if formset.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.member = self.request.user
                    instance.save()
        else:
            formset = UnavailableFormSet(
                queryset=qs)
        context['formset'] = formset
        return context
