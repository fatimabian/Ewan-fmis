from django import forms

from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.service_requests.models import ServiceRequest

from .models import Intervention


class InterventionForm(forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset())

    class Meta:
        model = Intervention
        fields = [
            "farmer", "service_request", "intervention_type", "intervention_date",
            "description", "quantity", "unit", "provider", "remarks",
        ]
        widgets = {
            "intervention_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.TextInput(attrs={"placeholder": "Describe what was provided"}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"service_request": "Related service request (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_ids = ServiceRequest.objects.filter(status="IN_PROGRESS").values_list("pk", flat=True)
        if self.instance and self.instance.pk and self.instance.service_request_id:
            request_ids = ServiceRequest.objects.filter(
                pk__in=[*request_ids, self.instance.service_request_id]
            ).values_list("pk", flat=True)
        self.fields["service_request"].queryset = ServiceRequest.objects.filter(
            pk__in=request_ids
        ).select_related("farmer", "service")
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
        if request and request.status != "IN_PROGRESS" and not (
            self.instance.pk and self.instance.service_request_id == request.pk
        ):
            self.add_error(
                "service_request",
                "Only an In Progress service request can proceed to an intervention.",
            )
        return cleaned
