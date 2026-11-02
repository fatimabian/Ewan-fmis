from uuid import uuid4

from django.conf import settings
from django.db import models

from .storage import private_storage


def scan_upload_path(instance, filename):
    """Random file name: the uploader's file name is never trusted or kept."""
    return f"form_scans/{uuid4().hex}.img"


class FormScan(models.Model):
    """One photographed farmer form, what OCR suggested, and what staff finally saved."""

    STATUS_DRAFT = "DRAFT"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_APPROVED = "APPROVED"
    STATUS_DISCARDED = "DISCARDED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Awaiting review"),
        (STATUS_CONFIRMED, "Confirmed, waiting to be saved in the form"),
        (STATUS_APPROVED, "Saved"),
        (STATUS_DISCARDED, "Discarded"),
        (STATUS_EXPIRED, "Not finished, cleared automatically"),
    ]
    OPEN_STATUSES = (STATUS_DRAFT, STATUS_CONFIRMED)
    TARGET_PARCEL = "PARCEL"
    TARGET_CROP = "CROP"
    TARGET_CHOICES = [(TARGET_PARCEL, "Farm parcel form"), (TARGET_CROP, "Commodity form")]
    LIGHT_CHOICES = [("GREEN", "Green"), ("YELLOW", "Yellow"), ("RED", "Red")]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="form_scans"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    image = models.FileField(upload_to=scan_upload_path, storage=private_storage, blank=True)
    # Set when the photos are deleted at the end of the scan cycle; the text audit trail stays.
    files_deleted_at = models.DateTimeField(null=True, blank=True)
    # Field groups staff chose not to use (for example "location"); their values are never carried to the form.
    rejected_groups = models.JSONField(default=list, blank=True)
    image_sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    # The form this scan fills in: it is opened with the confirmed values already entered.
    target = models.CharField(max_length=10, choices=TARGET_CHOICES, default=TARGET_PARCEL)
    ocr_available = models.BooleanField(default=False)
    ocr_provider = models.CharField(max_length=30, blank=True)
    ocr_model = models.CharField(max_length=120, blank=True)
    ocr_message = models.CharField(max_length=500, blank=True)
    # {field: {"value": str, "confidence": float}} exactly as the OCR answered; never edited.
    ocr_fields = models.JSONField(default=dict, blank=True)
    # {field: str}: the working values shown in the review form.
    fields = models.JSONField(default=dict, blank=True)
    drawn_polygon = models.JSONField(null=True, blank=True)
    traffic_light = models.CharField(max_length=6, choices=LIGHT_CHOICES, blank=True)
    checks = models.JSONField(default=list, blank=True)
    farmer = models.ForeignKey(
        "farmers.Farmer", null=True, blank=True, on_delete=models.SET_NULL, related_name="form_scans"
    )
    parcel = models.ForeignKey(
        "farm_parcels.FarmParcel", null=True, blank=True, on_delete=models.SET_NULL, related_name="form_scans"
    )
    crop = models.ForeignKey(
        "crops.CropRecord", null=True, blank=True, on_delete=models.SET_NULL, related_name="form_scans"
    )
    # Values handed to the target form once staff confirm the scan.
    prefill = models.JSONField(default=dict, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_form_scans"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Scan #{self.pk}"

    @property
    def page_numbers(self):
        """Page numbers that have a stored photo (1 is the first photo); none once the photos are deleted."""
        if self.files_deleted_at or not self.image:
            return []
        return [1, *[page.position for page in self.extra_pages.all()]]


class FormScanPage(models.Model):
    """Pages after the first of a multi page form (page one is FormScan.image)."""

    scan = models.ForeignKey(FormScan, on_delete=models.CASCADE, related_name="extra_pages")
    image = models.FileField(upload_to=scan_upload_path, storage=private_storage)
    image_sha256 = models.CharField(max_length=64)
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["scan", "position"], name="unique_scan_page_position")]


class FormScanAudit(models.Model):
    """Append only trail of what happened to a scan."""

    ACTION_CHOICES = [
        ("UPLOADED", "Uploaded"),
        ("OCR_DONE", "OCR read the form"),
        ("OCR_UNAVAILABLE", "OCR unavailable; manual entry"),
        ("CHECKED", "Checks re-run"),
        ("CONFIRMED", "Confirmed by staff"),
        ("SAVED", "Saved in the record"),
        ("DISCARDED", "Discarded"),
        ("EXPIRED", "Cleared automatically (not finished)"),
        ("FILES_DELETED", "Photos deleted"),
    ]

    scan = models.ForeignKey(FormScan, on_delete=models.CASCADE, related_name="audit")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class FieldCorrection(models.Model):
    """One OCR value that staff changed, kept for later learning (nothing is trained yet)."""

    scan = models.ForeignKey(FormScan, on_delete=models.CASCADE, related_name="corrections")
    field_name = models.CharField(max_length=40)
    ocr_value = models.CharField(max_length=250, blank=True)
    final_value = models.CharField(max_length=250, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    ocr_provider = models.CharField(max_length=30, blank=True)
    ocr_model = models.CharField(max_length=120, blank=True)
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scan_id", "field_name"]
