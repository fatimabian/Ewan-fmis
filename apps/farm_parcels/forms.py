from django import forms

from apps.common.constants import ROSARIO_BARANGAY_CHOICES
from apps.common.forms import InlineValidationMixin
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset

from .models import FarmParcel


class FarmParcelForm(InlineValidationMixin, forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset())
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES)
    farm_type = forms.CharField(
        max_length=30,
        required=False,
        label="Farm type",
        widget=forms.TextInput(attrs={"placeholder": "Remarks"}),
    )

    class Meta:
        model = FarmParcel
        fields = [
            "farmer", "barangay", "municipality", "province", "area_hectares", "ownership_type",
            "land_type", "farm_type", "ownership_document", "land_owner_name",
            "land_owner_registered_rsbsa", "within_ancestral_domain", "agrarian_reform_beneficiary",
            "is_rsbsa_recorded", "coordinates", "georef_id", "is_active",
        ]
        labels = {
            "farmer": "Existing Farmer ID / RSBSA Number",
            "area_hectares": "Total farm area (ha)",
            "ownership_type": "Ownership / tenure status",
            "ownership_document": "Proof of ownership / tenure",
            "land_owner_registered_rsbsa": "Land owner is registered in RSBSA",
            "within_ancestral_domain": "Within ancestral domain",
            "agrarian_reform_beneficiary": "Agrarian Reform Beneficiary (ARB)",
            "is_rsbsa_recorded": "Parcel already recorded in RSBSA",
            "coordinates": "GPS coordinates",
            "georef_id": "Georeference / GPX ID",
            "is_active": "Currently cultivated / active",
        }
        widgets = {"area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area_hectares"].min_value = 0.01
        self.fields["farmer"].queryset = active_farmer_queryset(self.instance.farmer_id if self.instance and self.instance.pk else None)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
