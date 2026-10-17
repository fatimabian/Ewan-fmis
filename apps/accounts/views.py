from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.utils import timezone
from uuid import uuid4
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.views import View
from apps.authentication.models import CustomUser
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from apps.activity_logs.services import record_request_event
from .forms import AccountForm, AccountUpdateForm
from .services import account_summary


class AccountListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = "accounts/list.html"

    def get_queryset(self):
        return CustomUser.objects.filter(deleted_at__isnull=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(account_summary())
        return context


class AccountDetailView(FMISLoginRequiredMixin, AdminRequiredMixin, DetailView):
    model = CustomUser
    template_name = "accounts/detail.html"

    def get_queryset(self):
        return CustomUser.objects.filter(deleted_at__isnull=True)


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

    def get_queryset(self):
        return CustomUser.objects.filter(deleted_at__isnull=True)

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

    def get_queryset(self):
        return CustomUser.objects.filter(deleted_at__isnull=True)

    def post(self, request, *args, **kwargs):
        account = self.get_object()
        requested_action = request.POST.get("action", "deactivate")
        restoring = requested_action == "restore"
        permanently_deleting = requested_action == "delete"
        if account.pk == request.user.pk and not restoring:
            messages.error(request, "You cannot deactivate or delete the account you are currently using.")
            return redirect("accounts:list")
        if (
            account.is_admin
            and not restoring
            and not CustomUser.objects.filter(role="ADMIN", is_active=True)
            .exclude(pk=account.pk)
            .exists()
        ):
            messages.error(request, "The final active administrator account cannot be deactivated or deleted.")
            return redirect("accounts:list")

        if permanently_deleting:
            account_label = account.display_name
            original_username = account.username
            account_role = account.get_role_display()
            account_status = "Active" if account.is_active else "Inactive"
            with transaction.atomic():
                account.deleted_display_name = account_label
                account.deleted_username = original_username
                account.deleted_at = timezone.now()
                account.username = f"deleted-{account.pk}-{uuid4().hex[:12]}"
                account.email = ""
                account.phone_number = ""
                account.google_sub = None
                account.is_active = False
                account.activation_pending = False
                account.mfa_enabled = False
                account.mfa_secret = ""
                account.mfa_recovery_codes = []
                account.mfa_last_counter = None
                account.mfa_version += 1
                account.set_unusable_password()
                account.save(
                    update_fields=(
                        "deleted_display_name",
                        "deleted_username",
                        "deleted_at",
                        "username",
                        "email",
                        "phone_number",
                        "google_sub",
                        "is_active",
                        "activation_pending",
                        "mfa_enabled",
                        "mfa_secret",
                        "mfa_recovery_codes",
                        "mfa_last_counter",
                        "mfa_version",
                        "password",
                    )
                )
                record_request_event(
                    request,
                    title="User Account Deleted",
                    module="User Accounts",
                    description=f"{request.user.display_name} permanently deleted a user account.",
                    target_label=account_label,
                    details=[
                        {"field": "Role", "before": account_role, "after": "Deleted"},
                        {"field": "Account status", "before": account_status, "after": "Deleted"},
                    ],
                )
            messages.success(
                request,
                f"{account_label}'s account was deleted and access was permanently removed. Its username, email address, and phone number can now be reused; linked office history was retained.",
            )
            return redirect("accounts:list")

        account.is_active = restoring
        account.mfa_version += 1
        account.save(update_fields=["is_active", "mfa_version"])
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


class AccountMFAResetView(FMISLoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        account = CustomUser.objects.filter(pk=pk, deleted_at__isnull=True).first()
        if not account:
            messages.error(request, "The account could not be found.")
            return redirect("accounts:list")
        if account.pk == request.user.pk:
            messages.error(
                request,
                "For safety, another administrator must reset MFA for the account you are using.",
            )
            return redirect("accounts:edit", pk=account.pk)
        account.mfa_enabled = False
        account.mfa_secret = ""
        account.mfa_recovery_codes = []
        account.mfa_last_counter = None
        account.mfa_version += 1
        account.save(
            update_fields=[
                "mfa_enabled",
                "mfa_secret",
                "mfa_recovery_codes",
                "mfa_last_counter",
                "mfa_version",
            ]
        )
        record_request_event(
            request,
            title="Multi-factor Authentication Reset",
            module="Security",
            description=f"{request.user.display_name} reset MFA for a user account.",
            target_label=account.display_name,
            details=[{"field": "MFA", "before": "Enabled", "after": "Enrollment required"}],
        )
        messages.success(
            request,
            f"MFA was reset for {account.display_name}. Existing sessions were revoked; the next sign-in requires new enrollment.",
        )
        return redirect("accounts:edit", pk=account.pk)
