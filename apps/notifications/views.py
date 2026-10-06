from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from apps.common.mixins import FMISLoginRequiredMixin

from .models import Notification


class NotificationListView(FMISLoginRequiredMixin, ListView):
    model = Notification
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 15

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related(
            "source_activity", "source_activity__actor"
        )


class NotificationOpenView(FMISLoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=("is_read", "read_at"))
        target = notification.url or reverse("notifications:list")
        if not url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            target = reverse("notifications:list")
        return redirect(target)


class NotificationMarkAllView(FMISLoginRequiredMixin, View):
    def post(self, request):
        Notification.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now(),
        )
        return redirect("notifications:list")
