from django.db.models import Q
from django.views.generic import ListView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.filters import parse_inclusive_date_range
from apps.common.permissions import AdminRequiredMixin
from apps.authentication.models import CustomUser
from .models import ActivityLog


class ActivityLogListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ActivityLog
    template_name = "activity_logs/list.html"
    def get_queryset(self):
        queryset = ActivityLog.objects.select_related("actor")
        query = self.request.GET.get("q", "").strip()
        module = self.request.GET.get("module", "").strip()
        user_id = self.request.GET.get("user", "").strip()
        date_range = parse_inclusive_date_range(self.request.GET, label="activity")
        self.filter_date_error = date_range.error
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(action__icontains=query)
            )
        if module:
            queryset = queryset.filter(module=module)
        if user_id.isdigit():
            queryset = queryset.filter(actor_id=int(user_id))
        if not date_range.error:
            if date_range.start:
                queryset = queryset.filter(created_at__date__gte=date_range.start)
            if date_range.end:
                queryset = queryset.filter(created_at__date__lte=date_range.end)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = (
            ActivityLog.objects.exclude(module="")
            .values_list("module", flat=True)
            .distinct()
            .order_by("module")
        )
        context["users"] = (
            CustomUser.objects.filter(activitylog__isnull=False)
            .distinct()
            .order_by("first_name", "last_name", "username")
        )
        context["filter_date_error"] = getattr(self, "filter_date_error", "")
        return context
