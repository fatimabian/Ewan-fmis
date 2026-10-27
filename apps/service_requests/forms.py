from django import forms
from django.urls import reverse
from apps.authentication.models import CustomUser
from apps.common.constants import CANONICAL_AGRICULTURAL_SERVICES
from apps.common.constants import ROSARIO_BARANGAY_CHOICES
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.service_catalog.models import ServiceCatalog
from apps.common.forms import InlineValidationMixin
from .models import ServiceLevelPolicy, ServiceRequest


class ServiceCatalogChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, service):
        return f"{service.name} — {service.category}"


class ServiceRequestForm(InlineValidationMixin, forms.ModelForm):
    BARANGAY_ONLY_SERVICE_CODES = frozenset({"TRAINING", "FCA"})
    farmer = FarmerChoiceField(queryset=active_farmer_queryset(), required=False)
    target_barangay = forms.ChoiceField(
        choices=ROSARIO_BARANGAY_CHOICES,
        required=False,
        label="Barangay",
    )
    service = ServiceCatalogChoiceField(
        queryset=ServiceCatalog.objects.none(),
        empty_label="Select an agricultural request type",
        label="Request Type",
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "scope", "farmer", "target_barangay", "service",
            "priority", "status", "notes", "assigned_to",
            "satisfaction_rating", "satisfaction_feedback", "feedback_method",
        ]
        labels = {
            "service": "Request Type",
            "assigned_to": "Assign to Staff",
            "notes": "Request Details",
            "satisfaction_rating": "Farmer Satisfaction (Optional)",
            "satisfaction_feedback": "Farmer Feedback (Optional)",
            "feedback_method": "Feedback Collection Method",
        }
        widgets = {
            "notes": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Add useful details about the service request..."}
            ),
            "satisfaction_rating": forms.Select(
                choices=[("", "No feedback recorded")] + [(value, f"{value} - {label}") for value, label in (
                    (1, "Very Dissatisfied"), (2, "Dissatisfied"), (3, "Neutral"),
                    (4, "Satisfied"), (5, "Very Satisfied"),
                )]
            ),
            "satisfaction_feedback": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        farmer_id = None
        if self.is_bound:
            farmer_id = self.data.get(self.add_prefix("farmer"))
        elif self.instance and self.instance.pk:
            farmer_id = self.instance.farmer_id
        active_farmers = active_farmer_queryset(farmer_id)
        if farmer_id and str(farmer_id).isdigit():
            self.fields["farmer"].queryset = active_farmers.filter(pk=farmer_id)
        else:
            self.fields["farmer"].queryset = active_farmers.none()
        self.fields["farmer"].widget.attrs["data-search-url"] = reverse(
            "interventions:farmer_search"
        )
        canonical_codes = [code for code, _name, _category in CANONICAL_AGRICULTURAL_SERVICES]
        services = ServiceCatalog.objects.filter(is_active=True, code__in=canonical_codes)
        if self.instance and self.instance.pk and self.instance.service_id:
            services = ServiceCatalog.objects.filter(
                pk__in=[*services.values_list("pk", flat=True), self.instance.service_id]
            )
        self.fields["service"].queryset = services.order_by("category", "name")
        barangay_only_values = services.filter(
            code__in=self.BARANGAY_ONLY_SERVICE_CODES
        ).values_list("pk", flat=True)
        self.fields["service"].widget.attrs["data-barangay-only-values"] = ",".join(
            str(value) for value in barangay_only_values
        )
        self.fields["assigned_to"].queryset = CustomUser.objects.filter(
            role="STAFF", is_active=True
        ).order_by("first_name", "last_name", "username")
        self.fields["assigned_to"].required = False
        # Preserve the original one-farmer behavior for older submissions that
        # predate the scope field. New browser submissions always include it.
        self.fields["scope"].required = False
        for field in ("satisfaction_rating", "satisfaction_feedback", "feedback_method"):
            self.fields[field].required = False

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope") or "INDIVIDUAL"
        cleaned["scope"] = scope
        farmer = cleaned.get("farmer")
        barangay = cleaned.get("target_barangay")
        service = cleaned.get("service")
        if scope == "INDIVIDUAL":
            cleaned["target_barangay"] = ""
            if not farmer:
                self.add_error("farmer", "Choose the farmer requesting this service.")
            if service and service.code in self.BARANGAY_ONLY_SERVICE_CODES:
                self.add_error(
                    "service",
                    "This request type is for barangay recipients. Choose Barangay as the scope.",
                )
        elif scope == "BARANGAY":
            cleaned["farmer"] = None
            if not barangay:
                self.add_error("target_barangay", "Choose the barangay requesting this service.")
            elif not active_farmer_queryset().filter(barangay=barangay).exists():
                self.add_error(
                    "target_barangay",
                    "This barangay has no active farmers. Choose a barangay with at least one active farmer.",
                )
        rating = cleaned.get("satisfaction_rating")
        feedback = (cleaned.get("satisfaction_feedback") or "").strip()
        method = (cleaned.get("feedback_method") or "").strip()
        if (rating or feedback or method) and cleaned.get("status") != "COMPLETED":
            self.add_error(
                "satisfaction_rating",
                "Farmer feedback can be recorded only after the request is completed.",
            )
        if rating and not method:
            self.add_error("feedback_method", "Record how the farmer feedback was collected.")
        return cleaned

    def save(self, commit=True):
        request = super().save(commit=False)
        request.subject = self.cleaned_data["service"].name
        if self.cleaned_data.get("satisfaction_rating"):
            from django.utils import timezone

            request.feedback_recorded_at = timezone.now()
        else:
            request.feedback_recorded_at = None
            request.feedback_recorded_by = None
        if commit:
            request.save()
            self.save_m2m()
        return request

    def clean_status(self):
        status = self.cleaned_data.get("status")
        has_registered_intervention = (
            self.instance.pk
            and self.instance.interventions.filter(is_active=True).exists()
        )
        if status == "COMPLETED" and not has_registered_intervention:
            raise forms.ValidationError(
                "Register this service request in Interventions before marking it Completed."
            )
        return status


class ServiceLevelPolicyForm(forms.ModelForm):
    class Meta:
        model = ServiceLevelPolicy
        fields = ("first_response_hours", "completion_hours", "is_approved")
        labels = {
            "first_response_hours": "First response (hours)",
            "completion_hours": "Completion (hours)",
            "is_approved": "Approved by OAS",
        }

    def clean(self):
        cleaned = super().clean()
        response = cleaned.get("first_response_hours")
        completion = cleaned.get("completion_hours")
        if response and completion and completion < response:
            self.add_error("completion_hours", "Completion must be later than first response.")
        return cleaned
