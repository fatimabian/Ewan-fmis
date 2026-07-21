from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from apps.authentication.models import CustomUser
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from .forms import AccountForm, AccountUpdateForm
from .services import account_summary


class AccountListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = "accounts/list.html"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs); context.update(account_summary()); return context


class AccountDetailView(FMISLoginRequiredMixin, AdminRequiredMixin, DetailView):
    model = CustomUser
    template_name = "accounts/detail.html"


class AccountCreateView(FMISLoginRequiredMixin, AdminRequiredMixin, CreateView):
    form_class = AccountForm
    template_name = "accounts/form.html"
    success_url = reverse_lazy("accounts:list")

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except IntegrityError:
            form.add_error("username", "This username is already in use. Please choose another username.")
            return self.form_invalid(form)
        messages.success(self.request, f"{self.object.display_name} can now sign in with the username and password you created.")
        return response


class AccountUpdateView(FMISLoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = CustomUser
    form_class = AccountUpdateForm
    template_name = "accounts/form.html"
    success_url = reverse_lazy("accounts:list")

    def form_valid(self, form):
        original_account = CustomUser.objects.get(pk=form.instance.pk)
        changing_admin_access = original_account.is_admin and (
            form.cleaned_data["role"] != "ADMIN" or not form.cleaned_data["is_active"]
        )
        if form.instance.pk == self.request.user.pk and changing_admin_access:
            form.add_error("role", "You cannot remove administrator access from the account you are currently using.")
            return self.form_invalid(form)
        if changing_admin_access and not CustomUser.objects.filter(role="ADMIN", is_active=True).exclude(pk=form.instance.pk).exists():
            form.add_error("role", "At least one active administrator account must remain.")
            return self.form_invalid(form)
        messages.success(self.request, f"{form.instance.display_name}'s account was updated.")
        return super().form_valid(form)


class AccountDeleteView(FMISLoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = CustomUser
    success_url = reverse_lazy("accounts:list")

    def post(self, request, *args, **kwargs):
        account = self.get_object()
        if account.pk == request.user.pk:
            messages.error(request, "You cannot delete the account you are currently using.")
            return redirect("accounts:list")
        if account.is_admin and not CustomUser.objects.filter(role="ADMIN", is_active=True).exclude(pk=account.pk).exists():
            messages.error(request, "The final active administrator account cannot be deleted.")
            return redirect("accounts:list")
        display_name = account.display_name
        account.delete()
        messages.success(request, f"{display_name}'s account was deleted.")
        return redirect("accounts:list")
