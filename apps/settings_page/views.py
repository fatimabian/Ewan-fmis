from django.contrib import messages
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import FormView
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.backups import create_verified_backup
from apps.common.permissions import AdminRequiredMixin
from apps.activity_logs.services import record_request_event
from .forms import ProfileForm
from .models import BackupRun, SystemSetting, UserPreference


class SettingsView(FMISLoginRequiredMixin, FormView):
    form_class = ProfileForm
    template_name = "settings/home.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        preference, _ = UserPreference.objects.get_or_create(
            user=self.request.user, defaults={"linked_email": self.request.user.email}
        )
        system_setting = SystemSetting.load()
        initial = {
            field: getattr(self.request.user, field)
            for field in ["first_name", "last_name", "email", "phone_number"]
        }
        initial.update(
            {
                field: getattr(preference, field)
                for field in [
                    "theme",
                    "primary_color",
                    "in_app_notifications",
                ]
            }
        )
        if self.request.user.is_admin:
            initial["automated_backups"] = system_setting.automated_backups
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_admin:
            last_backup = BackupRun.objects.first()
            context.update(
                {
                    "last_backup": last_backup,
                    "backup_retained_copies": (
                        last_backup.retained_copies
                        if last_backup and last_backup.status == "VERIFIED"
                        else 0
                    ),
                    "backup_encryption_configured": bool(settings.FMIS_BACKUP_ENCRYPTION_KEY),
                    "backup_offsite_configured": bool(settings.BACKUP_AZURE_CONTAINER_URL),
                    "backup_scheduler_configured": settings.FMIS_BACKUP_SCHEDULER_CONFIGURED,
                }
            )
        return context

    def form_valid(self, form):
        user_fields = ["first_name", "last_name", "email", "phone_number"]
        for field in user_fields:
            setattr(self.request.user, field, form.cleaned_data[field])
        self.request.user.save()
        preference, _ = UserPreference.objects.get_or_create(user=self.request.user)
        uploaded_photo = form.cleaned_data.get("profile_photo")
        remove_photo = form.cleaned_data.get("remove_profile_photo")
        old_photo_name = preference.profile_photo.name
        photo_storage = preference.profile_photo.storage
        if remove_photo:
            preference.profile_photo = ""
        elif uploaded_photo:
            preference.profile_photo = uploaded_photo
        for field in [
            "theme",
            "primary_color",
            "in_app_notifications",
        ]:
            setattr(preference, field, form.cleaned_data[field])
        preference.save()
        if old_photo_name and old_photo_name != preference.profile_photo.name:
            photo_storage.delete(old_photo_name)
        if self.request.user.is_admin:
            system_setting = SystemSetting.load()
            system_setting.automated_backups = form.cleaned_data["automated_backups"]
            system_setting.save(update_fields=("automated_backups", "updated_at"))
        messages.success(self.request, "Settings saved successfully.")
        return redirect("settings_page:home")


class ChangePasswordView(FMISLoginRequiredMixin, View):
    def post(self, request):
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"ok": True, "message": "Your password was changed successfully."}
                )
            messages.success(request, "Your password was changed successfully.")
        else:
            # Password mistakes belong beside their input fields. Returning the
            # same structured response for every client prevents the shared
            # message system from turning form validation into a modal.
            return JsonResponse(
                {
                    "ok": False,
                    "errors": {
                        name: [str(error) for error in errors]
                        for name, errors in form.errors.items()
                    },
                },
                status=400,
            )
        return redirect("settings_page:home")


class ManualBackupView(FMISLoginRequiredMixin, AdminRequiredMixin, View):
    """Create an encrypted, verified recovery point without exposing its file format."""

    def post(self, request):
        try:
            backup = create_verified_backup()
        except Exception:
            record_request_event(
                request,
                title="Backup Failed",
                module="Security",
                description="A manual backup attempt failed and requires technical review.",
                status="Failed",
                target_label="FMIS recovery backup",
            )
            messages.error(
                request,
                "The backup could not be completed. Review the protected server backup log or ask the technical administrator to check the configuration.",
            )
            return redirect("settings_page:home")

        record_request_event(
            request,
            title="Backup Verified",
            module="Security",
            description=f"{request.user.display_name} created a verified recovery backup.",
            target_label=backup.storage_label,
            details=[
                {"field": "Off-site copy", "after": "Yes" if backup.offsite else "No"},
                {"field": "Included media files", "after": backup.media_files},
            ],
        )

        if backup.offsite:
            messages.success(request, "Backup verified and stored in secure off-site storage.")
        else:
            messages.warning(
                request,
                "Backup verified in encrypted server storage. Configure off-site storage to complete disaster protection.",
            )
        return redirect("settings_page:home")
