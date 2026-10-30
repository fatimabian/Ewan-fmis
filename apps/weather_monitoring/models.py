from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class WeatherCoverageArea(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def clean(self):
        if not (13.6852949 <= float(self.latitude) <= 13.8700758):
            raise ValidationError({"latitude": "Choose a point within Rosario, Batangas."})
        if not (121.1638677 <= float(self.longitude) <= 121.3710798):
            raise ValidationError({"longitude": "Choose a point within Rosario, Batangas."})
        if float(self.radius_km) <= 0 or float(self.radius_km) > 15:
            raise ValidationError({"radius_km": "Coverage radius must be between 0 and 15 km."})

    def __str__(self):
        return self.name


class WeatherMonitoringRule(models.Model):
    PRIORITY_CHOICES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]
    name = models.CharField(max_length=120)
    coverage_area = models.ForeignKey(
        WeatherCoverageArea, on_delete=models.PROTECT, related_name="rules"
    )
    minimum_daily_rainfall_mm = models.DecimalField(max_digits=7, decimal_places=2)
    consecutive_days = models.PositiveSmallIntegerField(default=5)
    accumulated_rainfall_mm = models.DecimalField(max_digits=8, decimal_places=2)
    suggested_priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM"
    )
    cooldown_days = models.PositiveSmallIntegerField(default=7)
    recommended_action = models.CharField(
        max_length=500,
        default=(
            "Field inspection recommended due to prolonged rainfall. Please verify "
            "the condition of the identified farm parcels."
        ),
    )
    is_approved = models.BooleanField(
        default=False,
        help_text="OAS has formally approved this monitoring threshold.",
    )
    is_active = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_weather_rules",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["coverage_area__name", "name"]
        indexes = [models.Index(fields=["is_active", "is_approved"], name="weather_rule_active_idx")]

    def clean(self):
        if not 1 <= self.consecutive_days <= 14:
            raise ValidationError({"consecutive_days": "Use a period from 1 to 14 days."})
        if self.is_active and not self.is_approved:
            raise ValidationError({"is_active": "OAS approval is required before activation."})
        if self.is_active and not settings.FMIS_WEATHER_LICENSE_REVIEWED:
            raise ValidationError(
                {"is_active": "Confirm the weather API licence in the production environment first."}
            )

    def __str__(self):
        return f"{self.coverage_area}: {self.name}"


class WeatherObservation(models.Model):
    coverage_area = models.ForeignKey(
        WeatherCoverageArea, on_delete=models.CASCADE, related_name="observations"
    )
    observed_date = models.DateField()
    precipitation_mm = models.DecimalField(max_digits=8, decimal_places=2)
    source = models.CharField(max_length=180, default="Open-Meteo Best Match model estimate")
    source_url = models.URLField(max_length=500)
    retrieved_at = models.DateTimeField()
    resolved_latitude = models.DecimalField(max_digits=10, decimal_places=7)
    resolved_longitude = models.DecimalField(max_digits=10, decimal_places=7)
    is_complete = models.BooleanField(default=True)

    class Meta:
        ordering = ["-observed_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["coverage_area", "observed_date"], name="unique_weather_area_day"
            )
        ]
        indexes = [
            models.Index(fields=["coverage_area", "observed_date"], name="weather_obs_area_day_idx")
        ]


class WeatherRiskEvent(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_APPROVED = "APPROVED"
    STATUS_DISMISSED = "DISMISSED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Pending Weather Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DISMISSED, "Dismissed"),
    ]
    rule = models.ForeignKey(
        WeatherMonitoringRule, on_delete=models.PROTECT, related_name="events"
    )
    coverage_area = models.ForeignKey(
        WeatherCoverageArea, on_delete=models.PROTECT, related_name="events"
    )
    title = models.CharField(
        max_length=180,
        default="Prolonged rainfall detected — possible waterlogging risk.",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    accumulated_rainfall_mm = models.DecimalField(max_digits=8, decimal_places=2)
    suggested_priority = models.CharField(max_length=10)
    recommended_action = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    potentially_affected_parcels = models.ManyToManyField(
        "farm_parcels.FarmParcel", through="WeatherRiskParcel", related_name="weather_risk_events"
    )
    excluded_parcel_count = models.PositiveIntegerField(default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_weather_events",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.TextField(blank=True, max_length=1000)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_weather_events",
    )
    scheduled_for = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "coverage_area", "period_start", "period_end"],
                name="unique_weather_event_period",
            )
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="weather_event_status_idx")
        ]

    @property
    def event_id(self):
        return f"WR-{self.pk:04d}" if self.pk else "New weather event"


class WeatherRiskParcel(models.Model):
    event = models.ForeignKey(WeatherRiskEvent, on_delete=models.CASCADE, related_name="parcel_links")
    parcel = models.ForeignKey("farm_parcels.FarmParcel", on_delete=models.PROTECT)
    distance_km = models.DecimalField(max_digits=6, decimal_places=2)
    crop_summary = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "parcel"], name="unique_weather_event_parcel")
        ]


class WeatherEventRequest(models.Model):
    event = models.ForeignKey(WeatherRiskEvent, on_delete=models.PROTECT, related_name="request_links")
    service_request = models.OneToOneField(
        "service_requests.ServiceRequest", on_delete=models.PROTECT, related_name="weather_link"
    )
    barangay = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event", "barangay"], name="unique_weather_event_barangay")
        ]


class WeatherMonitoringRun(models.Model):
    STATUS_RUNNING = "RUNNING"
    STATUS_SUCCESS = "SUCCESS"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_PARTIAL, "Partial"),
        (STATUS_FAILED, "Failed"),
    ]
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    areas_checked = models.PositiveIntegerField(default=0)
    observations_saved = models.PositiveIntegerField(default=0)
    events_created = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["-started_at"]
