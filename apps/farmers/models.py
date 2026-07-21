from django.db import models
from django.utils import timezone


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
        ("PENDING", "Pending Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Needs Correction"),
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
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    civil_status = models.CharField(max_length=15, choices=CIVIL_STATUS_CHOICES, blank=True)
    spouse_name = models.CharField(max_length=180, blank=True)
    highest_education = models.CharField(max_length=120, blank=True)
    valid_id_type = models.CharField(max_length=100, blank=True)
    valid_id_number = models.CharField(max_length=100, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    is_indigenous = models.BooleanField(default=False)
    indigenous_group = models.CharField(max_length=120, blank=True)
    is_pwd = models.BooleanField(default=False)
    is_four_ps = models.BooleanField(default=False)
    livelihood = models.CharField(max_length=20, choices=LIVELIHOOD_CHOICES, default="FARMER")
    activities = models.TextField(blank=True, help_text="Comma-separated RSBSA livelihood activities")
    remarks = models.TextField(
        blank=True,
        max_length=1000,
        help_text="Internal agricultural-service notes; do not enter unsupported sensitive information.",
    )
    rsbsa_number = models.CharField(max_length=40, unique=True, null=True, blank=True)
    registration_status = models.CharField(
        max_length=12,
        choices=REGISTRATION_STATUS_CHOICES,
        default="APPROVED",
    )
    consent_given = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    photo = models.ImageField(upload_to="farmer_photos/", blank=True)
    location_coordinates = models.CharField(
        max_length=80,
        blank=True,
        help_text="Home location as latitude, longitude for the farmer map",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["last_name", "first_name"]

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
    def registration_reference(self):
        year = self.submitted_at.year if self.submitted_at else self.created_at.year
        return f"FR-{year}-{self.pk:06d}"

    @property
    def age(self):
        """Return completed years from birth date, or None when not recorded."""
        if not self.birth_date:
            return None
        today = timezone.localdate()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def primary_commodity(self):
        for parcel in self.parcels.all():
            crop = next(iter(parcel.crops.all()), None)
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

    def __str__(self):
        return f"{self.get_document_type_display()} - {self.farmer}"
