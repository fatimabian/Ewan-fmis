from django.conf import settings
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from apps.farmers.models import Farmer
from apps.service_catalog.models import ServiceCatalog


class ServiceLevelPolicy(models.Model):
    """Administrator-controlled proposed OAS service targets by priority."""

    PRIORITY_CHOICES = [("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")]
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, unique=True)
    first_response_hours = models.PositiveIntegerField()
    completion_hours = models.PositiveIntegerField()
    is_approved = models.BooleanField(
        default=False,
        help_text="OAS has formally approved this proposed service-level target.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_service_level_policies",
    )

    class Meta:
        ordering = ["priority"]

    def clean(self):
        if self.completion_hours < self.first_response_hours:
            raise ValidationError(
                {"completion_hours": "Completion time cannot be earlier than first response time."}
            )

    def __str__(self):
        return f"{self.get_priority_display()}: {self.first_response_hours}-{self.completion_hours} hours"


class ServiceRequest(models.Model):
    SCOPE_CHOICES = [
        ("INDIVIDUAL", "One farmer"),
        ("BARANGAY", "Barangay"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]
    PRIORITY_CHOICES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES, default="INDIVIDUAL")
    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.PROTECT,
        related_name="service_requests",
        null=True,
        blank=True,
    )
    target_barangay = models.CharField(max_length=100, blank=True)
    service = models.ForeignKey(ServiceCatalog, on_delete=models.PROTECT)
    subject = models.CharField(max_length=180, default="Agricultural service request")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_responded_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    first_response_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    satisfaction_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    satisfaction_feedback = models.CharField(max_length=500, blank=True)
    feedback_method = models.CharField(max_length=100, blank=True)
    feedback_recorded_at = models.DateTimeField(null=True, blank=True)
    feedback_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_service_feedback",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope="INDIVIDUAL",
                        farmer__isnull=False,
                        target_barangay="",
                    )
                    | (
                        models.Q(scope="BARANGAY", farmer__isnull=True)
                        & ~models.Q(target_barangay="")
                    )
                ),
                name="service_request_scope_target_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(satisfaction_rating__isnull=True)
                | models.Q(satisfaction_rating__gte=1, satisfaction_rating__lte=5),
                name="service_request_satisfaction_between_1_and_5",
            ),
        ]

    def _policy_hours(self):
        defaults = {
            "HIGH": (24, 72),
            "MEDIUM": (72, 96),
            "LOW": (120, 168),
        }
        try:
            policy = ServiceLevelPolicy.objects.filter(priority=self.priority).first()
        except Exception:
            policy = None
        return (
            (policy.first_response_hours, policy.completion_hours)
            if policy
            else defaults[self.priority]
        )

    def recalculate_deadlines(self, *, save=True):
        if not self.created_at:
            return
        response_hours, completion_hours = self._policy_hours()
        self.first_response_due_at = self.created_at + timedelta(hours=response_hours)
        self.due_at = self.created_at + timedelta(hours=completion_hours)
        if save:
            type(self).objects.filter(pk=self.pk).update(
                first_response_due_at=self.first_response_due_at,
                due_at=self.due_at,
            )

    def save(self, *args, **kwargs):
        creating = self._state.adding
        previous = None
        if not creating and self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("priority", "status").first()
        now = timezone.now()
        previous_status = previous["status"] if previous else None
        if self.status in {"IN_PROGRESS", "COMPLETED"} and not self.first_responded_at:
            self.first_responded_at = now
        if self.status == "COMPLETED" and previous_status != "COMPLETED":
            self.completed_at = now
        elif previous_status == "COMPLETED" and self.status != "COMPLETED":
            self.completed_at = None
        super().save(*args, **kwargs)
        if creating or (previous and previous["priority"] != self.priority):
            self.recalculate_deadlines()

    @property
    def overdue_kind(self):
        if self.status in {"COMPLETED", "CANCELLED"}:
            return ""
        now = timezone.now()
        if not self.first_responded_at and self.first_response_due_at and now > self.first_response_due_at:
            return "FIRST_RESPONSE"
        if self.due_at and now > self.due_at:
            return "COMPLETION"
        return ""

    @property
    def overdue_since(self):
        if self.overdue_kind == "FIRST_RESPONSE":
            return self.first_response_due_at
        if self.overdue_kind == "COMPLETION":
            return self.due_at
        return None

    @property
    def overdue_text(self):
        since = self.overdue_since
        if not since:
            return ""
        seconds = max(0, int((timezone.now() - since).total_seconds()))
        days = seconds // 86400
        hours = max(1, seconds // 3600)
        elapsed = f"{days} day{'s' if days != 1 else ''}" if days else f"{hours} hour{'s' if hours != 1 else ''}"
        target = "first response" if self.overdue_kind == "FIRST_RESPONSE" else "completion"
        return f"Request has been {elapsed} overdue for {target}."

    @property
    def timing_indicator(self):
        if self.overdue_kind:
            return "Overdue"
        if self.status in {"COMPLETED", "CANCELLED"}:
            return "Closed"
        now = timezone.now()
        next_due = self.first_response_due_at if not self.first_responded_at else self.due_at
        if next_due and now >= next_due - timedelta(hours=24):
            return "Due Soon"
        return "On Time"

    @property
    def request_id(self):
        return f"SR-{self.pk:04d}" if self.pk else "New"

    @property
    def beneficiary_label(self):
        if self.scope == "BARANGAY":
            return f"All active farmers in Brgy. {self.target_barangay}"
        if self.farmer_id:
            return self.farmer.list_name
        return "Beneficiary not specified"

    @property
    def beneficiary_reference(self):
        if self.scope == "BARANGAY":
            return f"Brgy. {self.target_barangay}"
        return self.farmer.record_id if self.farmer_id else "Not specified"

    def __str__(self):
        return f"{self.request_id} - {self.subject}"


class ServiceRequestHistory(models.Model):
    ACTION_CHOICES = [
        ("CREATED", "Created"),
        ("UPDATED", "Updated"),
        ("CANCELLED", "Cancelled"),
        ("REOPENED", "Reopened"),
        ("ESCALATED", "Escalated"),
    ]

    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_request_updates",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    changes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.service_request.request_id} - {self.get_action_display()}"


class ServiceRequestEscalation(models.Model):
    KIND_CHOICES = [
        ("FIRST_RESPONSE", "First response overdue"),
        ("COMPLETION", "Completion overdue"),
    ]
    service_request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="escalations"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    deadline = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=("service_request", "kind", "deadline"),
                name="unique_service_request_escalation_deadline",
            )
        ]
