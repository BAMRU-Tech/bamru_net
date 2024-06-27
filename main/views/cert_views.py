from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import modelform_factory
from django.forms import widgets
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import generic
from django.shortcuts import get_object_or_404


from rules.contrib.views import PermissionRequiredMixin

import collections
import jinja2

from main.models import Cert, CertSubType, CertType, DisplayCert, Member

class MemberCertListView(LoginRequiredMixin, generic.ListView):
    template_name = 'member_cert_list.html'
    context_object_name = 'cert_list'

    def get_queryset(self):
        qs = Cert.objects.filter(member=self.kwargs['pk'])
        qs = qs.select_related('subtype__type')
        qs = qs.order_by('subtype__type__position', 'subtype__position', '-expires_on', '-id')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = Member.objects.filter(id=self.kwargs['pk']).first()
        context['cert_types'] = [x.name for x in CertType.objects.all()]
        return context


class CertEditMixin(PermissionRequiredMixin, generic.edit.ModelFormMixin):
    model = Cert
    template_name = 'cert_form.html'
    permission_required = 'main.change_cert'
    queryset = Cert.objects.select_related('subtype__type')

    @property
    def cert_type(self):
        raise Exception  # subclasses must implement

    def get_member(self):
        raise Exception  # subclasses must implement

    def get_form_class(self):
        cert_type = self.cert_type

        fields = ['id', 'subtype']
        if cert_type.has_description:
            fields.append('description')
        if cert_type.has_earned_date:
            fields.append('earned_on')
        if cert_type.has_expiration_date:
            fields.append('expires_on')
        if cert_type.has_link:
            fields.append('link')
        if cert_type.has_file:
            fields.append('cert_file')
        fields.append('comment')
        return modelform_factory(
            Cert,
            fields=fields,
            widgets={
                'id': widgets.HiddenInput(),
                'type': widgets.HiddenInput(),
                'description': widgets.TextInput(),
                'comment': widgets.TextInput(),
                'link': widgets.TextInput(),
                'earned_on': widgets.DateInput(attrs={'type': 'date'}),
                'expires_on': widgets.DateInput(attrs={'type': 'date'}),
            },
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if 'cert_file' in self.request.FILES:
            f = self.request.FILES['cert_file']
            form.instance.cert_name = f.name
            form.instance.cert_size = f.size
            form.instance.cert_content_type = f.content_type
        form.fields['subtype'].queryset = CertSubType.objects.filter(
            type=self.cert_type).select_related('type')
        return form

    def form_valid(self, form):
        cert = form.save(commit=False)
        if not cert.subtype.is_other:
            cert.description = ''

        if not cert.member_id:
            cert.member_id = self.kwargs['member']

        # Check here for the add case
        if not self.request.user.has_perm('main.change_cert', cert):
            raise PermissionDenied

        cert.save()
        return HttpResponseRedirect(reverse('member_cert_list', args=[cert.member.id]))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['member'] = self.get_member()
        context['cert'] = Cert(type=self.cert_type)
        context['type'] = self.cert_type
        context['other_subtypes'] = [x.id for x in CertSubType.objects.filter(is_other=True)]
        return context


class CertCreateView(LoginRequiredMixin, CertEditMixin, generic.edit.CreateView):
    permission_required = 'main.add_cert'

    @cached_property
    def cert_type(self):
        name = self.request.GET.get('type')
        return CertType.objects.get(name=name)

    def get_member(self):
        return self.request.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['new'] = True
        context['cert'] = Cert(type=self.cert_type)
        return context

class CertEditView(LoginRequiredMixin, CertEditMixin, generic.edit.UpdateView):
    permission_required = 'main.change_cert'

    @cached_property
    def cert_type(self):
        return self.object.subtype.type

    def get_member(self):
        return self.object.member

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['new'] = False
        return context


class CertListView(LoginRequiredMixin, generic.TemplateView):
    template_name = 'cert_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cert_types'] = CertType.display_cert_types
        return context


@login_required
def cert_file_download_view(request, cert, **kwargs):
    c = get_object_or_404(Cert, id=cert)
    return download_file_helper(c.cert_file.url)

