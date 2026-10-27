from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.urls import reverse
from django.utils import timezone

from apps.notifications.models import Notification

from .models import ServiceLevelPolicy, ServiceRequest, ServiceRequestEscalation, ServiceRequestHistory


PROPOSED_POLICY_DEFAULTS = {
    "HIGH": (24, 72),
    "MEDIUM": (72, 96),
    "LOW": (120, 168),
}


def ensure_service_level_policies():
    policies = []
    for priority, (response_hours, completion_hours) in PROPOSED_POLICY_DEFAULTS.items():
        policy, _ = ServiceLevelPolicy.objects.get_or_create(
            priority=priority,
            defaults={
                "first_response_hours": response_hours,
                "completion_hours": completion_hours,
                "is_approved": False,
            },
        )
        policies.append(policy)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(policies, key=lambda item: order[item.priority])


def recalculate_open_deadlines():
    """Recalculate open targets in three bounded database updates."""
    updated = 0
    for policy in ensure_service_level_policies():
        updated += ServiceRequest.objects.filter(priority=policy.priority).exclude(
            status__in=("COMPLETED", "CANCELLED")
        ).update(
            first_response_due_at=ExpressionWrapper(
                F("created_at") + timedelta(hours=policy.first_response_hours),
                output_field=ServiceRequest._meta.get_field("first_response_due_at"),
            ),
            due_at=ExpressionWrapper(
                F("created_at") + timedelta(hours=policy.completion_hours),
                output_field=ServiceRequest._meta.get_field("due_at"),
            ),
        )
    return updated


@transaction.atomic
def update_status(request_obj, status):
    request_obj.status = status
    request_obj.save()
    return request_obj


def _duration_label(value):
    if value is None:
        return "N/A"
    hours = max(0, value.total_seconds()) / 3600
    return f"{hours:.1f} hours" if hours < 48 else f"{hours / 24:.1f} days"


def service_effectiveness_metrics(queryset=None, *, start=None, cutoff=None):
    """Calculate elapsed-time indicators from requests created in one cohort."""
    cutoff = cutoff or timezone.now()
    queryset = queryset if queryset is not None else ServiceRequest.objects.all()
    cohort = queryset.filter(created_at__lte=cutoff)
    if start is not None:
        cohort = cohort.filter(created_at__gte=start)

    response_duration = ExpressionWrapper(
        F("first_responded_at") - F("created_at"), output_field=DurationField()
    )
    turnaround_duration = ExpressionWrapper(
        F("completed_at") - F("created_at"), output_field=DurationField()
    )
    response_average = cohort.filter(
        first_responded_at__isnull=False, first_responded_at__gte=F("created_at")
    ).aggregate(value=Avg(response_duration))["value"]
    turnaround_average = cohort.filter(
        status="COMPLETED", completed_at__isnull=False, completed_at__gte=F("created_at")
    ).aggregate(value=Avg(turnaround_duration))["value"]
    totals = cohort.aggregate(
        total=Count("pk"),
        completed=Count("pk", filter=Q(status="COMPLETED", completed_at__lte=cutoff)),
        unanswered=Count(
            "pk",
            filter=Q(first_responded_at__isnull=True) & ~Q(status__in=("COMPLETED", "CANCELLED")),
        ),
    )
    open_requests = queryset.filter(created_at__lte=cutoff).exclude(
        status__in=("COMPLETED", "CANCELLED")
    )
    overdue_filter = (
        Q(first_responded_at__isnull=True, first_response_due_at__lt=cutoff)
        | Q(first_responded_at__isnull=False, due_at__lt=cutoff)
    )
    open_summary = open_requests.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status="PENDING")),
        in_progress=Count("pk", filter=Q(status="IN_PROGRESS")),
        overdue=Count("pk", filter=overdue_filter),
    )
    aging = {
        "0_1_days": open_requests.filter(created_at__gte=cutoff - timedelta(days=2)).count(),
        "2_3_days": open_requests.filter(created_at__lt=cutoff - timedelta(days=2), created_at__gte=cutoff - timedelta(days=4)).count(),
        "4_7_days": open_requests.filter(created_at__lt=cutoff - timedelta(days=4), created_at__gte=cutoff - timedelta(days=8)).count(),
        "over_7_days": open_requests.filter(created_at__lt=cutoff - timedelta(days=8)).count(),
    }
    satisfaction = cohort.filter(satisfaction_rating__isnull=False).aggregate(
        average=Avg("satisfaction_rating"), responses=Count("pk")
    )
    resolution_rate = round(totals["completed"] / totals["total"] * 100, 1) if totals["total"] else None
    return {
        "average_response": response_average,
        "average_response_display": _duration_label(response_average),
        "average_turnaround": turnaround_average,
        "average_turnaround_display": _duration_label(turnaround_average),
        "resolution_rate": resolution_rate,
        "resolution_rate_display": f"{resolution_rate:.1f}%" if resolution_rate is not None else "N/A",
        "cohort_total": totals["total"],
        "cohort_completed": totals["completed"],
        "unanswered": totals["unanswered"],
        "open_backlog": open_summary["total"],
        "pending": open_summary["pending"],
        "in_progress": open_summary["in_progress"],
        "overdue": open_summary["overdue"],
        "aging": aging,
        "satisfaction_average": satisfaction["average"],
        "satisfaction_display": f"{satisfaction['average']:.1f} / 5" if satisfaction["average"] is not None else "No feedback",
        "satisfaction_responses": satisfaction["responses"],
        "uses_elapsed_time": True,
    }


def _notification_recipients(service_request):
    user_model = get_user_model()
    ids = set(
        user_model.objects.filter(
            Q(role="ADMIN") | Q(is_superuser=True), is_active=True
        ).values_list("pk", flat=True)
    )
    if service_request.assigned_to_id and service_request.assigned_to.is_active:
        ids.add(service_request.assigned_to_id)
    return user_model.objects.filter(pk__in=ids).filter(
        Q(preferences__in_app_notifications=True) | Q(preferences__isnull=True)
    )


@transaction.atomic
def process_due_escalations(*, now=None):
    """Idempotently record and notify newly overdue open requests."""
    now = now or timezone.now()
    candidates = (
        ServiceRequest.objects.select_for_update()
        .select_related("assigned_to")
        .exclude(status__in=("COMPLETED", "CANCELLED"))
        .filter(
            Q(first_responded_at__isnull=True, first_response_due_at__lt=now)
            | Q(first_responded_at__isnull=False, due_at__lt=now)
        )
    )
    created_count = 0
    notification_count = 0
    for item in candidates:
        kind = item.overdue_kind
        deadline = item.first_response_due_at if kind == "FIRST_RESPONSE" else item.due_at
        if not kind or not deadline:
            continue
        _escalation, created = ServiceRequestEscalation.objects.get_or_create(
            service_request=item, kind=kind, deadline=deadline
        )
        if not created:
            continue
        created_count += 1
        reason = item.overdue_text
        ServiceRequestHistory.objects.create(
            service_request=item,
            actor=None,
            action="ESCALATED",
            from_status=item.status,
            to_status=item.status,
            changes=[{"field": "Service target", "before": "On time", "after": reason}],
        )
        for recipient in _notification_recipients(item):
            target = reverse("activity_logs:list") if recipient.is_admin else reverse("service_requests:detail", args=[item.pk])
            Notification.objects.create(
                recipient=recipient,
                title=f"{item.request_id} is overdue",
                message=reason[:255],
                category="warning",
                url=target,
            )
            notification_count += 1
    return {"escalations": created_count, "notifications": notification_count}
