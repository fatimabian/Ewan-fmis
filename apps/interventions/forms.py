from django import forms

from apps.common.constants import ROSARIO_BARANGAY_CHOICES
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest

from .models import Intervention


class FarmerMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, farmer):
        return f"{farmer.record_id} - {farmer.list_name} ({farmer.barangay})"


class InterventionForm(forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset(), required=False)
    selected_farmers = FarmerMultipleChoiceField(
        queryset=Farmer.objects.none(),
        required=False,
        label="Specific farmers",
        widget=forms.CheckboxSelectMultiple(attrs={"class": "intervention-checkbox-list"}),
        help_text="Choose every farmer included in this intervention.",
    )
    target_barangay = forms.ChoiceField(
        choices=ROSARIO_BARANGAY_CHOICES, required=False, label="Barangay"
    )

    class Meta:
        model = Intervention
        fields = [
            "scope", "farmer", "selected_farmers", "target_barangay", "service_request",
            "status", "intervention_type", "intervention_date",
            "description", "quantity", "unit", "provider",
        ]
        widgets = {
            "intervention_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.TextInput(attrs={"placeholder": "Describe what was provided"}),
        }
        labels = {"service_request": "Related service request (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_farmers = active_farmer_queryset()
        self.fields["scope"].required = False
        self.fields["status"].required = False
        self.fields["scope"].initial = self.instance.scope or "INDIVIDUAL"
        self.fields["status"].initial = self.instance.status or "COMPLETED"
        self.fields["selected_farmers"].queryset = active_farmers
        if self.instance and self.instance.pk:
            self.fields["selected_farmers"].initial = self.instance.recipients.filter(
                is_active=True
            ).values_list("farmer_id", flat=True)
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
        scope = cleaned.get("scope") or "INDIVIDUAL"
        cleaned["scope"] = scope
        cleaned["status"] = cleaned.get("status") or "COMPLETED"
        selected = cleaned.get("selected_farmers")
        barangay = cleaned.get("target_barangay")
        if scope == "INDIVIDUAL" and not farmer:
            self.add_error("farmer", "Choose the farmer receiving this intervention.")
        if scope == "SELECTED" and not selected:
            self.add_error("selected_farmers", "Choose at least one farmer.")
        if scope == "BARANGAY" and not barangay:
            self.add_error("target_barangay", "Choose the barangay covered by this intervention.")
        if request and scope != "INDIVIDUAL":
            self.add_error(
                "service_request", "A service request can only be linked to a one-farmer intervention."
            )
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
