from django import forms

from apps.common.forms import InlineValidationMixin
from apps.interventions.models import Intervention

from .models import InventoryItem, InventoryMovement


class InventoryItemForm(InlineValidationMixin, forms.ModelForm):
    class Meta:
        model = InventoryItem
        fields = (
            "item_code",
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

    def clean_item_code(self):
        code = self.cleaned_data.get("item_code", "").strip().upper()
        queryset = InventoryItem.objects.filter(item_code__iexact=code)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("This item code is already in use.")
        return code


class InventoryMovementForm(InlineValidationMixin, forms.Form):
    item = forms.ModelChoiceField(queryset=InventoryItem.objects.none())
    movement_type = forms.ChoiceField(choices=InventoryMovement.MOVEMENT_CHOICES)
    quantity = forms.DecimalField(min_value=0.01, max_digits=14, decimal_places=2)
    intervention = forms.ModelChoiceField(
        queryset=Intervention.objects.none(),
        required=False,
        empty_label="N/A — not linked to an intervention",
    )
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
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = InventoryItem.objects.filter(is_active=True).order_by(
            "name", "item_code"
        )
        self.fields["intervention"].queryset = Intervention.objects.filter(
            is_active=True
        ).order_by("-intervention_date", "-pk")

    def clean(self):
        cleaned = super().clean()
        movement_type = cleaned.get("movement_type")
        intervention = cleaned.get("intervention")
        if movement_type == InventoryMovement.RELEASE and intervention is None:
            self.add_error(
                "intervention",
                "Choose the intervention receiving this stock release.",
            )
        return cleaned
