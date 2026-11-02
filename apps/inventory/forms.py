from django import forms
from django.db.models import Q

from apps.common.forms import InlineValidationMixin
from apps.interventions.models import Intervention
from apps.service_requests.models import ServiceRequest

from .models import InventoryItem, InventoryMovement


INVENTORY_UNIT_CHOICES = (
    ("", "Select a unit"),
    ("pcs", "Pieces (pcs)"),
    ("kg", "Kilograms (kg)"),
    ("g", "Grams (g)"),
    ("L", "Liters (L)"),
    ("mL", "Milliliters (mL)"),
    ("bag", "Bags"),
    ("sack", "Sacks"),
    ("box", "Boxes"),
    ("pack", "Packs"),
    ("bottle", "Bottles"),
    ("pair", "Pairs"),
    ("set", "Sets"),
    ("unit", "Units"),
)


class InterventionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, intervention):
        request = (
            f" — {intervention.service_request.request_id}"
            if intervention.service_request_id
            else " — Direct intervention"
        )
        return f"{intervention.reference_id} — {intervention.beneficiary_label}{request}"


class InventoryItemForm(InlineValidationMixin, forms.ModelForm):
    unit = forms.ChoiceField(
        choices=INVENTORY_UNIT_CHOICES,
        label="Unit",
        help_text="Choose the unit used for receipts, releases, and the on-hand balance.",
    )
    opening_quantity = forms.DecimalField(
        label="Initial stock on hand",
        min_value=0,
        max_digits=14,
        decimal_places=2,
        help_text="Enter the quantity physically on hand when this item is first added.",
    )

    def __init__(self, *args, **kwargs):
        creating = kwargs.pop("creating", False)
        super().__init__(*args, **kwargs)
        # Preserve older custom units when an existing record is edited, while
        # keeping all newly created items on the standard unit list.
        current_unit = getattr(self.instance, "unit", "")
        if current_unit and current_unit not in dict(self.fields["unit"].choices):
            self.fields["unit"].choices = (
                *self.fields["unit"].choices,
                (current_unit, f"{current_unit} (existing unit)"),
            )
        if not creating:
            self.fields.pop("opening_quantity", None)
        self.order_fields(
            (
                "name",
                "category",
                "unit",
                "opening_quantity",
                "reorder_level",
                "storage_location",
                "expiration_date",
                "notes",
            )
        )

    class Meta:
        model = InventoryItem
        fields = (
            "name",
            "category",
            "unit",
            "reorder_level",
            "storage_location",
            "expiration_date",
            "notes",
        )
        widgets = {
            "expiration_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

class InventoryMovementForm(InlineValidationMixin, forms.Form):
    service_request = forms.ModelChoiceField(
        queryset=ServiceRequest.objects.none(),
        required=False,
        empty_label="N/A — no related service request",
        label="Related service request",
        help_text="For a requested release, choose the request being fulfilled.",
    )
    intervention = InterventionChoiceField(
        queryset=Intervention.objects.none(),
        required=False,
        empty_label="N/A — create from the selected request",
        label="Related intervention",
    )
    item = forms.ModelChoiceField(queryset=InventoryItem.objects.none())
    movement_type = forms.ChoiceField(choices=InventoryMovement.MOVEMENT_CHOICES)
    quantity = forms.DecimalField(min_value=0.01, max_digits=14, decimal_places=2)
    reference = forms.CharField(
        required=False,
        max_length=100,
        help_text="Optional delivery receipt, purchase order, or office reference.",
    )
    remarks = forms.CharField(
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = (
            InventoryItem.objects.filter(is_active=True)
            .only("pk", "item_code", "name")
            .order_by("name", "item_code")
        )
        requests = ServiceRequest.objects.filter(
            status__in=("PENDING", "IN_PROGRESS", "COMPLETED")
        ).select_related("farmer", "service")
        interventions = Intervention.objects.filter(
            is_active=True, status="COMPLETED"
        ).select_related("farmer", "service_request")
        if self.user:
            requests = requests.filter(assigned_to=self.user)
            interventions = interventions.filter(
                Q(service_request__assigned_to=self.user)
                | Q(service_request__isnull=True, recorded_by=self.user)
            )
        self.fields["service_request"].queryset = requests.order_by("-created_at", "-pk")
        self.fields["intervention"].queryset = interventions.order_by(
            "-intervention_date", "-pk"
        )
        self.fields["intervention"].widget.attrs["data-linked-interventions"] = "true"

    def clean(self):
        cleaned = super().clean()
        movement_type = cleaned.get("movement_type")
        service_request = cleaned.get("service_request")
        intervention = cleaned.get("intervention")
        if (
            service_request
            and intervention
            and intervention.service_request_id != service_request.pk
        ):
            self.add_error(
                "intervention",
                "Choose an intervention linked to the selected service request.",
            )
        if (
            movement_type == InventoryMovement.RELEASE
            and intervention is None
            and service_request is None
        ):
            self.add_error(
                "intervention",
                "Choose a related service request or an existing intervention for this release.",
            )
        return cleaned
