from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class InventoryItem(models.Model):
    CATEGORY_CHOICES = [
        ("SEEDS", "Seeds / planting materials"),
        ("FERTILIZER", "Fertilizer / soil inputs"),
        ("CROP_PROTECTION", "Crop protection supplies"),
        ("VETERINARY", "Veterinary / livestock supplies"),
        ("TOOLS", "Tools and equipment"),
        ("MACHINERY", "Machinery"),
        ("OTHER", "Other agricultural supplies"),
    ]

    item_code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES)
    unit = models.CharField(max_length=40, help_text="For example: bag, kilogram, unit, or liter")
    stock_on_hand = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    reorder_level = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)]
    )
    storage_location = models.CharField(max_length=160)
    expiration_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, max_length=1000)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "item_code"]
        indexes = [
            models.Index(fields=["is_active", "category"], name="inventory_active_cat_idx"),
            models.Index(fields=["expiration_date"], name="inventory_expiry_idx"),
        ]

    @property
    def stock_status(self):
        if self.stock_on_hand <= 0:
            return "OUT_OF_STOCK"
        if self.expiration_date and self.expiration_date <= timezone.localdate() + timedelta(days=30):
            return "EXPIRING"
        if self.stock_on_hand <= self.reorder_level:
            return "LOW_STOCK"
        return "IN_STOCK"

    @property
    def stock_status_label(self):
        return {
            "OUT_OF_STOCK": "Out of stock",
            "EXPIRING": "Expiring soon",
            "LOW_STOCK": "Low stock",
            "IN_STOCK": "In stock",
        }[self.stock_status]

    @property
    def stock_status_css(self):
        return self.stock_status.lower().replace("_", "-")

    def __str__(self):
        return f"{self.item_code} — {self.name}"


class InventoryMovement(models.Model):
    RECEIPT = "RECEIPT"
    RELEASE = "RELEASE"
    RETURN = "RETURN"
    ADJUST_IN = "ADJUST_IN"
    ADJUST_OUT = "ADJUST_OUT"
    DAMAGED = "DAMAGED"
    EXPIRED = "EXPIRED"
    MOVEMENT_CHOICES = [
        (RECEIPT, "Stock received"),
        (RELEASE, "Released for intervention"),
        (RETURN, "Stock returned"),
        (ADJUST_IN, "Positive adjustment"),
        (ADJUST_OUT, "Negative adjustment"),
        (DAMAGED, "Damaged stock"),
        (EXPIRED, "Expired stock"),
    ]
    INBOUND_TYPES = {RECEIPT, RETURN, ADJUST_IN}
    OUTBOUND_TYPES = {RELEASE, ADJUST_OUT, DAMAGED, EXPIRED}

    item = models.ForeignKey(
        InventoryItem, on_delete=models.PROTECT, related_name="movements"
    )
    movement_type = models.CharField(max_length=16, choices=MOVEMENT_CHOICES)
    quantity = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    intervention = models.ForeignKey(
        "interventions.Intervention",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )
    reference = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True, max_length=1000)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="inventory_movements_recorded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["item", "created_at"], name="inventory_item_date_idx"),
            models.Index(fields=["movement_type", "created_at"], name="inventory_move_date_idx"),
        ]

    @property
    def movement_id(self):
        return f"STK-{self.pk:05d}" if self.pk else "New"

    @property
    def signed_quantity(self):
        return self.quantity if self.movement_type in self.INBOUND_TYPES else -self.quantity

    def __str__(self):
        return f"{self.movement_id} — {self.item.name}"
