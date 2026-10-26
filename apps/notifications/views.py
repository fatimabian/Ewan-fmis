from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from apps.common.mixins import FMISLoginRequiredMixin

from .models import Notification
from .services import notification_target


class NotificationListView(FMISLoginRequiredMixin, ListView):
    model = Notification
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related(
            "source_activity", "source_activity__actor"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for notification in context["notifications"]:
            target = notification_target(notification, self.request.user)
            if not url_has_allowed_host_and_scheme(
                target,
                allowed_hosts={self.request.get_host()},
                require_https=self.request.is_secure(),
            ) or target == reverse("notifications:list"):
                target = ""
            notification.target_url = target
        return context


class NotificationOpenView(FMISLoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=("is_read", "read_at"))
        target = notification_target(notification, request.user)
        if not url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            target = reverse("notifications:list")
        if request.headers.get("Accept") == "application/json":
            return JsonResponse({"ok": True, "target": target})
        return redirect(target)


class NotificationMarkAllView(FMISLoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
        return redirect("notifications:list")
