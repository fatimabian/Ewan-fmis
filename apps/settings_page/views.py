"""Account preferences and administrator backup/recovery actions."""

import time
import secrets
import mimetypes
import uuid
from pathlib import Path

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.core.cache import cache
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import FormView
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.backups import (
    create_verified_backup,
    offsite_backup_configured,
    verify_existing_backup,
)
from apps.common.permissions import AdminRequiredMixin
from apps.activity_logs.services import record_request_event
from .forms import ProfileForm, SettingsPasswordChangeForm
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
        context.setdefault(
            "password_form",
            SettingsPasswordChangeForm(user=self.request.user),
        )
        context.setdefault(
            "profile_modal_open",
            self.request.GET.get("modal") == "contact",
        )
        context.setdefault(
            "password_modal_open",
            self.request.GET.get("modal") == "password",
        )
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
                    "backup_offsite_configured": offsite_backup_configured(),
                    "backup_scheduler_configured": settings.FMIS_BACKUP_SCHEDULER_CONFIGURED,
                }
            )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("settings_action") == "password":
            password_form = SettingsPasswordChangeForm(
                user=request.user,
                data=request.POST,
            )
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed successfully.")
                return redirect("settings_page:home")
            profile_form = self.form_class(
                user=request.user,
                initial=self.get_initial(),
            )
            return self.render_to_response(
                self.get_context_data(
                    form=profile_form,
                    password_form=password_form,
                    password_modal_open=True,
                )
            )
        return super().post(request, *args, **kwargs)

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
        action = self.request.POST.get("settings_action")
        if action == "profile":
            messages.success(self.request, "Contact information updated successfully.")
        elif action != "preferences":
            messages.success(self.request, "Settings saved successfully.")
        return redirect("settings_page:home")

    def form_invalid(self, form):
        return self.render_to_response(
            self.get_context_data(form=form, profile_modal_open=True)
        )


class ChangePasswordView(FMISLoginRequiredMixin, FormView):
    form_class = SettingsPasswordChangeForm
    template_name = "settings/password_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        user = form.save()
        update_session_auth_hash(self.request, user)
        messages.success(self.request, "Your password was changed successfully.")
        return redirect("settings_page:home")


class ProfilePhotoView(FMISLoginRequiredMixin, View):
    """Serve a user's own profile image without exposing the media directory."""

    def get(self, request):
        preference = UserPreference.objects.filter(user=request.user).first()
        if not preference or not preference.profile_photo:
            raise Http404
        try:
            content_type = (
                mimetypes.guess_type(preference.profile_photo.name)[0]
                or "application/octet-stream"
            )
            response = FileResponse(
                preference.profile_photo.open("rb"),
                content_type=content_type,
            )
        except (FileNotFoundError, OSError, ValueError) as error:
            raise Http404 from error
        response["Content-Disposition"] = "inline"
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


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

        response = FileResponse(
            backup.path.open("rb"), as_attachment=True,
            filename=backup.archive_name, content_type="application/octet-stream",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Backup-Storage"] = "offsite" if backup.offsite else "server"
        return response


class PrepareRestoreView(FMISLoginRequiredMixin, AdminRequiredMixin, View):
    """Password-gate, authenticate, and stage a recovery archive for maintenance restore."""

    max_upload_bytes = 2 * 1024 * 1024 * 1024

    def post(self, request):
        """Unlock for five minutes, then authenticate a selected archive once."""
        def error(field, message, status=400):
            response = JsonResponse({"ok": False, "errors": {field: message}}, status=status)
            response["Cache-Control"] = "no-store"
            return response

        action = request.POST.get("restore_action", "prepare")
        if action == "unlock":
            request.session.pop("restore_authorization", None)
            password = request.POST.get("restore_password", "")
            if not password:
                return error("restore_password", "Enter your administrator password.")
            rate_key = f"restore-unlock:{request.user.pk}"
            failures = cache.get(rate_key, 0)
            if failures >= 5:
                return error("restore_password", "Too many attempts. Try again in five minutes.", 429)
            if not request.user.check_password(password):
                cache.set(rate_key, failures + 1, 300)
                return error("restore_password", "Your administrator password is incorrect.")
            cache.delete(rate_key)
            token = secrets.token_urlsafe(32)
            request.session["restore_authorization"] = {
                "expires": time.time() + 300,
                "auth_hash": request.user.get_session_auth_hash(),
                "token": token,
            }
            return JsonResponse({"ok": True, "token": token})

        authorization = request.session.get("restore_authorization", {})
        if (
            authorization.get("expires", 0) < time.time()
            or authorization.get("auth_hash") != request.user.get_session_auth_hash()
            or not secrets.compare_digest(str(authorization.get("token", "")), request.POST.get("restore_token", ""))
        ):
            request.session.pop("restore_authorization", None)
            return error("restore_password", "Verify your administrator password again.", 403)
        archive = request.FILES.get("restore_archive")
        if not archive or not archive.name.lower().endswith(".fmisbak"):
            return error("restore_archive", "Choose an FMIS encrypted backup file (.fmisbak).")
        if archive.size > self.max_upload_bytes:
            return error("restore_archive", "The selected file exceeds the 2 GB upload limit.")

        staging_root = Path(settings.BACKUP_ROOT).expanduser().resolve() / "restore-staging"
        staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        staged_path = staging_root / f"restore-{uuid.uuid4().hex}.fmisbak"
        try:
            with staged_path.open("xb") as output:
                staged_path.chmod(0o600)
                for chunk in archive.chunks():
                    output.write(chunk)
            checksum = verify_existing_backup(staged_path)
        except Exception:
            staged_path.unlink(missing_ok=True)
            record_request_event(
                request,
                title="Restore Preparation Failed",
                module="Security",
                description="An uploaded recovery archive failed authentication.",
                status="Failed",
                target_label="FMIS recovery restore",
            )
            return error("restore_archive", "FMIS could not authenticate this backup. No live records were changed.")

        record_request_event(
            request,
            title="Restore Package Prepared",
            module="Security",
            description=f"{request.user.display_name} authenticated a recovery archive for maintenance restore.",
            target_label=staged_path.name,
            details=[{"field": "SHA-256", "after": checksum}],
        )
        request.session.pop("restore_authorization", None)
        response = JsonResponse({
            "ok": True,
            "message": "Recovery package verified and prepared successfully. No live records were changed. A technical administrator can apply it during maintenance.",
        })
        response["Cache-Control"] = "no-store"
        return response
