from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.http import FileResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import FormView
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.backups import create_verified_backup
from apps.common.permissions import AdminRequiredMixin
from .forms import ProfileForm
from .models import UserPreference
from .models import SystemSetting
class SettingsView(FMISLoginRequiredMixin, FormView):
    form_class = ProfileForm; template_name = "settings/home.html"
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs
    def get_initial(self):
        preference, _ = UserPreference.objects.get_or_create(user=self.request.user, defaults={"linked_email": self.request.user.email})
        system_setting = SystemSetting.load()
        initial = {field: getattr(self.request.user, field) for field in ["first_name", "last_name", "email", "phone_number"]}
        initial.update({field: getattr(preference, field) for field in ["theme", "primary_color", "email_notifications", "in_app_notifications", "weekly_summary", "two_factor_enabled"]})
        if self.request.user.is_admin:
            initial.update({"system_name": system_setting.system_name, "timezone": system_setting.timezone, "default_language": system_setting.default_language, "session_timeout": str(system_setting.session_timeout), "automated_backups": system_setting.automated_backups, "two_factor_required": system_setting.two_factor_required})
        return initial
    def form_valid(self, form):
        user_fields = ["first_name", "last_name", "email", "phone_number"]
        for field in user_fields: setattr(self.request.user, field, form.cleaned_data[field])
        self.request.user.save()
        preference, _ = UserPreference.objects.get_or_create(user=self.request.user)
        for field in ["theme", "primary_color", "email_notifications", "in_app_notifications", "weekly_summary", "two_factor_enabled"]: setattr(preference, field, form.cleaned_data[field])
        preference.save()
        if self.request.user.is_admin:
            system_setting = SystemSetting.load()
            for field in ["system_name", "timezone", "default_language", "automated_backups", "two_factor_required"]: setattr(system_setting, field, form.cleaned_data[field])
            system_setting.session_timeout = int(form.cleaned_data["session_timeout"])
            system_setting.save()
            cache.delete("fmis:session-timeout-minutes")
        messages.success(self.request, "Settings saved successfully."); return redirect("settings_page:home")


class ChangePasswordView(FMISLoginRequiredMixin, View):
    def post(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "message": "Your password was changed successfully."})
            messages.success(request, "Your password was changed successfully.")
        else:
            # Password mistakes belong beside their input fields. Returning the
            # same structured response for every client prevents the shared
            # message system from turning form validation into a modal.
            return JsonResponse({
                "ok": False,
                "errors": {name: [str(error) for error in errors] for name, errors in form.errors.items()},
            }, status=400)
        return redirect("settings_page:home")


class ManualBackupView(FMISLoginRequiredMixin, AdminRequiredMixin, View):
    """Create a verified server copy and return the same archive to the administrator."""

    def post(self, request):
        try:
            backup = create_verified_backup()
        except (OSError, RuntimeError, ValueError) as error:
            messages.error(request, f"The manual backup could not be completed: {error}")
            return redirect("settings_page:home")

        response = FileResponse(
            backup.path.open("rb"),
            as_attachment=True,
            filename=backup.path.name,
            content_type="application/gzip",
        )
        response["X-FMIS-Backup-Status"] = "verified"
        response["X-FMIS-Backup-Records"] = str(backup.record_count)
        return response
