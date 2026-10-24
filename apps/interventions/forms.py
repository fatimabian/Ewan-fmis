from django import forms
from django.urls import reverse

from apps.common.forms import InlineValidationMixin
from apps.common.constants import ROSARIO_BARANGAY_CHOICES
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest

from .models import Intervention
from .services import INTERVENTION_TYPE_BY_SERVICE_CODE


class FarmerMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, farmer):
        return f"{farmer.record_id} - {farmer.list_name} ({farmer.barangay})"


class RelatedServiceRequestSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        request = getattr(value, "instance", None)
        if request:
            option["attrs"]["data-intervention-type"] = (
                INTERVENTION_TYPE_BY_SERVICE_CODE.get(request.service.code, "OTHER")
            )
            option["attrs"]["data-scope"] = request.scope
            option["attrs"]["data-farmer-id"] = str(request.farmer_id or "")
            option["attrs"]["data-target-barangay"] = request.target_barangay
        return option


class ServiceRequestChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, request):
        return (
            f"{request.request_id} — {request.beneficiary_label} — "
            f"{request.service.name} ({request.get_status_display()})"
        )


class InterventionForm(InlineValidationMixin, forms.ModelForm):
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
    service_request = ServiceRequestChoiceField(
        queryset=ServiceRequest.objects.none(),
        required=False,
        empty_label="N/A — no related service request",
        label="Related service request",
        widget=RelatedServiceRequestSelect,
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
        labels = {"service_request": "Related service request"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_farmers = active_farmer_queryset()
        farmer_search_url = reverse("interventions:farmer_search")
        self.fields["farmer"].widget.attrs["data-search-url"] = farmer_search_url
        self.fields["scope"].required = False
        self.fields["status"].required = True
        self.fields["status"].choices = [("", "---------"), *Intervention.STATUS_CHOICES]
        self.fields["scope"].initial = self.instance.scope or "INDIVIDUAL"
        if not self.instance.pk and not self.is_bound:
            self.initial["status"] = ""
        selected_ids = []
        if self.is_bound:
            selected_key = self.add_prefix("selected_farmers")
            if hasattr(self.data, "getlist"):
                selected_ids = self.data.getlist(selected_key)
            else:
                selected_ids = self.data.get(selected_key, [])
                if not isinstance(selected_ids, (list, tuple)):
                    selected_ids = [selected_ids]
            farmer_id = self.data.get(self.add_prefix("farmer"))
        else:
            farmer_id = self.initial.get("farmer")
            farmer_id = getattr(farmer_id, "pk", farmer_id)
        if self.instance and self.instance.pk:
            selected_ids = list(self.instance.recipients.filter(
                is_active=True
            ).values_list("farmer_id", flat=True))
            self.fields["selected_farmers"].initial = selected_ids
            farmer_id = farmer_id or self.instance.farmer_id
        valid_selected_ids = [value for value in selected_ids if str(value).isdigit()]
        self.fields["selected_farmers"].queryset = active_farmers.filter(
            pk__in=valid_selected_ids
        )
        self.fields["selected_farmers"].widget.attrs["data-search-url"] = farmer_search_url
        if farmer_id and str(farmer_id).isdigit():
            self.fields["farmer"].queryset = active_farmers.filter(pk=farmer_id)
        else:
            self.fields["farmer"].queryset = Farmer.objects.none()
        request_ids = ServiceRequest.objects.filter(
            status__in=("PENDING", "IN_PROGRESS")
        ).values_list("pk", flat=True)
        if self.instance and self.instance.pk and self.instance.service_request_id:
            request_ids = ServiceRequest.objects.filter(
                pk__in=[*request_ids, self.instance.service_request_id]
            ).values_list("pk", flat=True)
        self.fields["service_request"].queryset = ServiceRequest.objects.filter(
            pk__in=request_ids
        ).select_related("farmer", "service").order_by("-created_at", "-pk")
        self.fields["service_request"].required = False
        self.fields["service_request"].help_text = (
            "Choose the request being fulfilled, or select N/A when the intervention was not requested."
        )

    def clean(self):
        cleaned = super().clean()
        request = cleaned.get("service_request")
        submitted_scope = cleaned.get("scope") or "INDIVIDUAL"
        scope = submitted_scope
        if request:
            expected_type = INTERVENTION_TYPE_BY_SERVICE_CODE.get(
                request.service.code, "OTHER"
            )
            if submitted_scope != request.scope:
                self.add_error(
                    "scope",
                    "Coverage must match the related service request.",
                )
            if (
                request.scope == "INDIVIDUAL"
                and cleaned.get("farmer") != request.farmer
            ):
                self.add_error(
                    "farmer",
                    "Farmer must match the related service request.",
                )
            if (
                request.scope == "BARANGAY"
                and cleaned.get("target_barangay") != request.target_barangay
            ):
                self.add_error(
                    "target_barangay",
                    f"Barangay must remain {request.target_barangay} because it is set by the related service request.",
                )
            if cleaned.get("intervention_type") != expected_type:
                self.add_error(
                    "intervention_type",
                    "Intervention type must match the related service request.",
                )
            scope = request.scope
            cleaned["farmer"] = request.farmer if scope == "INDIVIDUAL" else None
            cleaned["target_barangay"] = (
                request.target_barangay if scope == "BARANGAY" else ""
            )
            cleaned["intervention_type"] = expected_type
        cleaned["scope"] = scope
        farmer = cleaned.get("farmer")
        selected = cleaned.get("selected_farmers")
        barangay = cleaned.get("target_barangay")
        if scope == "INDIVIDUAL" and not farmer:
            self.add_error("farmer", "Choose the farmer receiving this intervention.")
        if scope == "SELECTED" and not selected:
            self.add_error("selected_farmers", "Choose at least one farmer.")
        if scope == "BARANGAY" and not barangay:
            self.add_error("target_barangay", "Choose the barangay covered by this intervention.")
        elif scope == "BARANGAY" and not active_farmer_queryset().filter(
            barangay=barangay
        ).exists():
            self.add_error(
                "target_barangay",
                "This barangay has no active farmers. Choose a barangay with at least one active farmer.",
            )
        if scope == "ALL" and not active_farmer_queryset().exists():
            self.add_error(
                "scope",
                "There are no active farmers to receive this intervention.",
            )
        if request and request.status not in {"PENDING", "IN_PROGRESS"} and not (
            self.instance.pk and self.instance.service_request_id == request.pk
        ):
            self.add_error(
                "service_request",
                "Only a Pending or In Progress service request can be linked to an intervention.",
            )
        return cleaned
