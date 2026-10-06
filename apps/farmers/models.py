from django.core.validators import RegexValidator
from django.conf import settings
from django.db import models
from django.utils import timezone

PH_MOBILE_VALIDATOR = RegexValidator(
    regex=r"^09\d{9}$",
    message="Enter a valid PH mobile number: 11 digits, starting with 09 (e.g. 09171234567).",
)


class Farmer(models.Model):
    SEX_CHOICES = [("MALE", "Male"), ("FEMALE", "Female")]
    CIVIL_STATUS_CHOICES = [
        ("SINGLE", "Single"),
        ("MARRIED", "Married"),
        ("WIDOWED", "Widowed"),
        ("SEPARATED", "Separated"),
    ]
    LIVELIHOOD_CHOICES = [
        ("FARMER", "Farmer"),
        ("FARMWORKER", "Farm Worker / Laborer"),
        ("FISHERFOLK", "Fisherfolk"),
        ("AGRI_YOUTH", "Agri-Youth"),
    ]
    REGISTRATION_STATUS_CHOICES = [
        ("ENCODED", "Encoded"),
        ("SUBMITTED", "Submitted"),
        ("SKIPPED", "Skipped"),
        ("COMPLETED", "Completed"),
    ]

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    extension_name = models.CharField(max_length=20, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    place_of_birth = models.CharField(max_length=180, blank=True)
    house_lot_purok = models.CharField(max_length=120, blank=True)
    street_sitio = models.CharField(max_length=120, blank=True)
    barangay = models.CharField(max_length=100)
    city_municipality = models.CharField(max_length=100, default="Rosario")
    province = models.CharField(max_length=100, default="Batangas")
    region = models.CharField(max_length=100, default="CALABARZON Region IV-A")
    mother_maiden_name = models.CharField(max_length=180, blank=True)
    phone_number = models.CharField(max_length=11, blank=True, validators=[PH_MOBILE_VALIDATOR])
    email = models.EmailField(blank=True)
    civil_status = models.CharField(max_length=15, choices=CIVIL_STATUS_CHOICES, blank=True)
    spouse_name = models.CharField(max_length=180, blank=True)
    highest_education = models.CharField(max_length=120, blank=True)
    valid_id_type = models.CharField(max_length=100, blank=True)
    valid_id_number = models.CharField(max_length=100, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    is_indigenous = models.BooleanField(null=True, blank=True, default=None)
    indigenous_group = models.CharField(max_length=120, blank=True)
    is_pwd = models.BooleanField(null=True, blank=True, default=None)
    is_four_ps = models.BooleanField(null=True, blank=True, default=None)
    livelihood = models.CharField(max_length=20, choices=LIVELIHOOD_CHOICES, default="FARMER")
    activities = models.TextField(
        blank=True, help_text="Comma-separated RSBSA livelihood activities"
    )
    remarks = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Internal agricultural-service notes; do not enter unsupported sensitive information.",
    )
    rsbsa_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    registration_status = models.CharField(
        max_length=12,
        choices=REGISTRATION_STATUS_CHOICES,
        default="ENCODED",
    )
    consent_given = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    photo = models.ImageField(upload_to="farmer_photos/", blank=True)
    location_coordinates = models.CharField(
        max_length=80,
        blank=True,
        help_text="Home location as latitude, longitude for the farmer map",
    )
    philsys_registered = models.BooleanField(null=True, blank=True)
    philsys_pcn = models.CharField(max_length=50, blank=True)
    philsys_trn = models.CharField(max_length=50, blank=True)
    fca_membership = models.CharField(max_length=180, blank=True)
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_updated_farmers",
    )
    last_updated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(registration_status="COMPLETED")
                    & models.Q(rsbsa_number__isnull=False)
                    & ~models.Q(rsbsa_number="")
                )
                | (
                    ~models.Q(registration_status="COMPLETED")
                    & (models.Q(rsbsa_number__isnull=True) | models.Q(rsbsa_number=""))
                ),
                name="farmer_rsbsa_id_matches_completed_status",
            )
        ]

    @property
    def full_name(self):
        middle = f" {self.middle_name}" if self.middle_name else ""
        extension = f" {self.extension_name}" if self.extension_name else ""
        return f"{self.first_name}{middle} {self.last_name}{extension}".strip()

    @property
    def list_name(self):
        extension = f" {self.extension_name}" if self.extension_name else ""
        middle = f" {self.middle_name}" if self.middle_name else ""
        return f"{self.last_name}{extension}, {self.first_name}{middle}".strip()

    @property
    def record_id(self):
        return f"F-{self.pk:04d}" if self.pk else "New"

    @property
    def photo_available(self):
        """Avoid rendering a broken media URL when a legacy file is missing."""
        if not self.photo or not self.photo.name:
            return False
        try:
            return self.photo.storage.exists(self.photo.name)
        except (OSError, ValueError):
            return False

    @property
    def registration_reference(self):
        year = self.submitted_at.year if self.submitted_at else self.created_at.year
        return f"FR-{year}-{self.pk:06d}"

    @property
    def activities_display(self):
        labels = {
            "FARMER_CROPS": "Farmer - Crops", "FARMER_LIVESTOCK": "Farmer - Livestock",
            "FARMER_POULTRY": "Farmer - Poultry", "WORK_LAND_PREPARATION": "Farm Worker - Land Preparation",
            "WORK_PLANTING": "Farm Worker - Planting / Transplanting", "WORK_CULTIVATION": "Farm Worker - Cultivation",
            "WORK_HARVESTING": "Farm Worker - Harvesting", "FISH_CAPTURE": "Fisherfolk - Fish Capture",
            "FISH_AQUACULTURE": "Fisherfolk - Aquaculture", "FISH_GLEANING": "Fisherfolk - Gleaning",
            "FISH_PROCESSING": "Fisherfolk - Processing", "FISH_VENDING": "Fisherfolk - Vending",
            "YOUTH_HOUSEHOLD": "Agri-Youth - Farming Household Member", "YOUTH_FORMAL": "Agri-Youth - Formal Agriculture Course",
            "YOUTH_NONFORMAL": "Agri-Youth - Non-formal Agriculture Course", "YOUTH_PROGRAM": "Agri-Youth - Agriculture Activity / Program",
        }
        values = [value.strip() for value in self.activities.split(",") if value.strip()]
        return ", ".join(labels.get(value, value.replace("_", " ").title()) for value in values)

    @property
    def age(self):
        """Return completed years from birth date, or None when not recorded."""
        if not self.birth_date:
            return None
        today = timezone.localdate()
        return (
            today.year
            - self.birth_date.year
            - ((today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        )

    @property
    def primary_commodity(self):
        for parcel in self.parcels.all():
            crop = next(iter(parcel.crops.filter(is_active=True)), None)
            if crop:
                return crop.crop_type
        return "Not recorded"

    def __str__(self):
        return self.full_name


class FarmerDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ("VALID_ID", "Valid ID"),
        ("PROOF_OF_ADDRESS", "Proof of Address"),
        ("OWNERSHIP", "Ownership / Tenure Document"),
        ("ADDITIONAL", "Additional Supporting Document"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    description = models.CharField(max_length=180, blank=True)
    file = models.FileField(upload_to="farm_documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def file_available(self):
        """Return False for legacy database rows whose uploaded file was removed."""
        if not self.file or not self.file.name:
            return False
        try:
            return self.file.storage.exists(self.file.name)
        except (OSError, ValueError):
            return False

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.farmer}"


class FarmerUpdateHistory(models.Model):
    UPDATE_TYPE_CHOICES = [
        ("SLIP_A", "Slip A - Personal Information"),
        ("SLIP_B", "Slip B - Farm Parcel Information"),
        ("STATUS", "Office Registration Status"),
    ]
    CHANGE_REASON_CHOICES = [
        ("CORRECTION", "A - Correction"),
        ("REMOVAL", "B - Removal"),
        ("ADDITION", "C - Additional / New Information"),
        ("OTHER", "Other"),
    ]

    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.CASCADE,
        related_name="update_history",
    )
    update_type = models.CharField(max_length=10, choices=UPDATE_TYPE_CHOICES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmer_updates",
    )
    transaction_code = models.CharField(max_length=80, blank=True)
    change_reason = models.CharField(
        max_length=20,
        choices=CHANGE_REASON_CHOICES,
        default="CORRECTION",
    )
    remarks = models.TextField(blank=True)
    date_signed = models.DateField(null=True, blank=True)
    date_received = models.DateField(null=True, blank=True)
    agriculturist_name = models.CharField(max_length=180, blank=True)
    snapshot_before = models.JSONField(default=dict)
    snapshot_after = models.JSONField(default=dict)
    changes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name_plural = "farmer update histories"

    def __str__(self):
        return f"{self.get_update_type_display()} - {self.farmer}"
