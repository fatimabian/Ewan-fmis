from django.db import models


class ServiceCatalog(models.Model):
    ICON_CHOICES = [
        ("bi-flask", "Laboratory testing"),
        ("bi-flower1", "Crops and planting"),
        ("bi-droplet", "Water and irrigation"),
        ("bi-bug", "Pest management"),
        ("bi-tools", "Equipment and repair"),
        ("bi-box-seam", "Farm inputs"),
        ("bi-mortarboard", "Training and seminars"),
        ("bi-clipboard2-check", "Registration and certification"),
        ("bi-shop", "Market assistance"),
        ("bi-heart-pulse", "Animal and livestock care"),
        ("bi-people", "Farmer support"),
        ("bi-journal-text", "General agricultural service"),
    ]
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True)
    category = models.CharField(max_length=100)
    description = models.TextField(max_length=500)
    processing_time = models.CharField(max_length=100)
    requirements = models.TextField(blank=True)
    service_type = models.CharField(max_length=100, blank=True)
    target_beneficiaries = models.CharField(max_length=255, blank=True)
    office_responsible = models.CharField(max_length=150, blank=True)
    availability = models.CharField(max_length=100, blank=True)
    seasonality = models.CharField(max_length=100, blank=True)
    icon = models.ImageField(upload_to="service_icons/", blank=True)
    icon_name = models.CharField(max_length=40, choices=ICON_CHOICES, default="bi-journal-text")
    badge_color = models.CharField(max_length=7, default="#008552")
    tags = models.CharField(max_length=255, blank=True)
    notes = models.TextField(max_length=300, blank=True)
    internal_remarks = models.TextField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
