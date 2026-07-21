from django.db.models import Q
from django.views.generic import ListView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from .models import ActivityLog


class ActivityLogListView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ActivityLog
    template_name = "activity_logs/list.html"
    paginate_by = 10

    def get_queryset(self):
        queryset = ActivityLog.objects.select_related("actor")
        query = self.request.GET.get("q", "").strip()
        module = self.request.GET.get("module", "").strip()
        user_id = self.request.GET.get("user", "").strip()
        if query:
            queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(action__icontains=query))
        if module:
            queryset = queryset.filter(module=module)
        if user_id:
            queryset = queryset.filter(actor_id=user_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modules"] = ActivityLog.objects.exclude(module="").values_list("module", flat=True).distinct().order_by("module")
        context["users"] = ActivityLog.objects.filter(actor__isnull=False).select_related("actor").order_by("actor__username")
        return context
