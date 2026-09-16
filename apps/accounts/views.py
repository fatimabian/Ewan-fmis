from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from apps.authentication.models import CustomUser
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from apps.activity_logs.services import record_request_event
from .forms import AccountForm, AccountUpdateForm
from .services import account_summary


class AccountListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = "accounts/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(account_summary())
        return context


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
            form.add_error(
                "username", "This username is already in use. Please choose another username."
            )
            return self.form_invalid(form)
        record_request_event(
            self.request,
            title="User Account Created",
            module="User Accounts",
            description=f"{self.request.user.display_name} created a staff account.",
            target_label=self.object.display_name,
            details=[
                {"field": "Role", "after": self.object.get_role_display()},
                {"field": "Status", "after": "Pending activation"},
            ],
        )
        messages.success(
            self.request,
            (
                f"{self.object.display_name}'s staff account was created. "
                "It will activate after the user verifies the email OTP on first sign-in."
            ),
        )
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
            form.add_error(
                "role",
                "You cannot remove administrator access from the account you are currently using.",
            )
            return self.form_invalid(form)
        if (
            changing_admin_access
            and not CustomUser.objects.filter(role="ADMIN", is_active=True)
            .exclude(pk=form.instance.pk)
            .exists()
        ):
            form.add_error("role", "At least one active administrator account must remain.")
            return self.form_invalid(form)
        response = super().form_valid(form)
        changes = []
        if original_account.role != self.object.role:
            changes.append({
                "field": "Role",
                "before": original_account.get_role_display(),
                "after": self.object.get_role_display(),
            })
        if original_account.is_active != self.object.is_active:
            changes.append({
                "field": "Account status",
                "before": "Active" if original_account.is_active else "Inactive",
                "after": "Active" if self.object.is_active else "Inactive",
            })
        record_request_event(
            self.request,
            title="User Account Updated",
            module="User Accounts",
            description=f"{self.request.user.display_name} updated a user account.",
            target_label=self.object.display_name,
            details=changes,
        )
        messages.success(self.request, f"{form.instance.display_name}'s account was updated.")
        return response


class AccountDeleteView(FMISLoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = CustomUser
    success_url = reverse_lazy("accounts:list")

    def post(self, request, *args, **kwargs):
        account = self.get_object()
        restoring = request.POST.get("action") == "restore"
        if account.pk == request.user.pk and not restoring:
            messages.error(request, "You cannot deactivate the account you are currently using.")
            return redirect("accounts:list")
        if (
            account.is_admin
            and not CustomUser.objects.filter(role="ADMIN", is_active=True)
            .exclude(pk=account.pk)
            .exists()
        ):
            messages.error(request, "The final active administrator account cannot be deactivated.")
            return redirect("accounts:list")
        account.is_active = restoring
        account.save(update_fields=["is_active"])
        action = "reactivated" if restoring else "deactivated"
        record_request_event(
            request,
            title=f"User Account {action.title()}",
            module="User Accounts",
            description=f"{request.user.display_name} {action} a user account.",
            target_label=account.display_name,
            details=[{
                "field": "Account status",
                "before": "Inactive" if restoring else "Active",
                "after": "Active" if restoring else "Inactive",
            }],
        )
        messages.success(request, f"{account.display_name}'s account was {action}; its history was preserved.")
        return redirect("accounts:list")
