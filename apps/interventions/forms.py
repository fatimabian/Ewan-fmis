from django import forms
from django.urls import reverse
from django.db.models import Count

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
            option["attrs"]["data-target-association"] = request.target_association
            option["attrs"]["data-walk-in-name"] = request.walk_in_name
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
    target_association = forms.ChoiceField(
        choices=(), required=False, label="Association"
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
            "scope", "farmer", "selected_farmers", "target_barangay",
            "target_association", "walk_in_name", "service_request",
            "intervention_type", "description", "quantity", "unit", "provider",
        ]
        widgets = {
            "description": forms.TextInput(attrs={"placeholder": "Describe what was provided"}),
        }
        labels = {"service_request": "Related service request"}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        active_farmers = active_farmer_queryset()
        farmer_search_url = reverse("interventions:farmer_search")
        self.fields["farmer"].widget.attrs["data-search-url"] = farmer_search_url
        self.fields["scope"].required = False
        self.fields["scope"].initial = self.instance.scope or "INDIVIDUAL"
        association_rows = (
            Farmer.objects.filter(is_active=True, is_association_member=True)
            .exclude(fca_membership="")
            .values("fca_membership")
            .annotate(member_count=Count("pk"))
            .order_by("fca_membership")
        )
        association_choices = [
            (
                row["fca_membership"],
                f'{row["fca_membership"]} ({row["member_count"]} active member'
                f'{"s" if row["member_count"] != 1 else ""})',
            )
            for row in association_rows
        ]
        current_association = self.instance.target_association if self.instance.pk else ""
        if current_association and current_association not in {
            value for value, _label in association_choices
        }:
            association_choices.append(
                (current_association, f"{current_association} (no active members)")
            )
        self.fields["target_association"].choices = [
            ("", "Select an association"),
            *association_choices,
        ]
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
        )
        if self.user:
            request_ids = request_ids.filter(
                assigned_to=self.user
            )
        request_ids = request_ids.values_list("pk", flat=True)
        if self.instance and self.instance.pk and self.instance.service_request_id:
            request_ids = ServiceRequest.objects.filter(
                pk__in=[*request_ids, self.instance.service_request_id]
            ).values_list("pk", flat=True)
        self.fields["service_request"].queryset = ServiceRequest.objects.filter(
            pk__in=request_ids
        ).select_related("farmer", "service").order_by("-created_at", "-pk")
        self.fields["service_request"].required = False
        if self.instance.pk and self.instance.service_request_id:
            self.fields["service_request"].disabled = True
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
            scope = request.scope
            cleaned["farmer"] = request.farmer if scope == "INDIVIDUAL" else None
            cleaned["target_barangay"] = (
                request.target_barangay if scope == "BARANGAY" else ""
            )
            cleaned["target_association"] = (
                request.target_association if scope == "ASSOCIATION" else ""
            )
            cleaned["walk_in_name"] = (
                request.walk_in_name if scope == "WALK_IN" else ""
            )
            cleaned["intervention_type"] = expected_type
        cleaned["scope"] = scope
        farmer = cleaned.get("farmer")
        selected = cleaned.get("selected_farmers")
        barangay = cleaned.get("target_barangay")
        association = (cleaned.get("target_association") or "").strip()
        walk_in_name = (cleaned.get("walk_in_name") or "").strip()
        if scope != "BARANGAY":
            cleaned["target_barangay"] = ""
        if scope != "ASSOCIATION":
            cleaned["target_association"] = ""
        if scope != "WALK_IN":
            cleaned["walk_in_name"] = ""
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
        if scope == "ASSOCIATION" and not association:
            self.add_error(
                "target_association",
                "Choose the association covered by this intervention.",
            )
        elif scope == "ASSOCIATION" and not active_farmer_queryset().filter(
            is_association_member=True,
            fca_membership=association,
        ).exists():
            self.add_error(
                "target_association",
                "This association has no active farmer members.",
            )
        if scope == "WALK_IN" and not walk_in_name:
            self.add_error("walk_in_name", "Enter the walk-in recipient's name.")
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
