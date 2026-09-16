from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect

from apps.activity_logs.services import record_request_event


class RoleRequiredMixin(UserPassesTestMixin):
    denied_message = "That page is not available for your account role."

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        record_request_event(
            self.request,
            title="Access denied",
            module="Security",
            description=f"{self.request.user.display_name} attempted to open a role-restricted page.",
            status="Warning",
            target_label=self.request.path,
        )
        messages.warning(self.request, self.denied_message)
        return redirect("dashboard:home")


class AdminRequiredMixin(RoleRequiredMixin):
    denied_message = "This page is available to administrators only."

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_admin


class StaffRequiredMixin(RoleRequiredMixin):
    """Allow FMIS staff accounts while explicitly rejecting administrators."""

    denied_message = "This operational page is available to staff accounts only."

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and not user.is_admin and user.role == "STAFF"
