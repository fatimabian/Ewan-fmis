from django import forms

from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset

from .models import Intervention


class InterventionForm(forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset())

    class Meta:
        model = Intervention
        fields = [
            "farmer", "service_request", "intervention_type", "intervention_date",
            "description", "quantity", "unit", "estimated_value", "funding_source",
            "provider", "remarks", "is_active",
        ]
        widgets = {
            "intervention_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.TextInput(attrs={"placeholder": "Describe what was provided"}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"is_active": "Active record", "service_request": "Related service request (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service_request"].queryset = self.fields["service_request"].queryset.select_related("farmer", "service")
        self.fields["service_request"].required = False
        self.fields["service_request"].help_text = (
            "Link the assistance to the request it fulfills, when applicable."
        )

    def clean(self):
        cleaned = super().clean()
        request = cleaned.get("service_request")
        farmer = cleaned.get("farmer")
        if request and farmer and request.farmer_id != farmer.pk:
            self.add_error("service_request", "Choose a request belonging to the selected farmer.")
        return cleaned
