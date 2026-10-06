from django import forms
from apps.authentication.models import CustomUser
from apps.common.constants import CANONICAL_AGRICULTURAL_SERVICES
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.service_catalog.models import ServiceCatalog
from apps.common.forms import InlineValidationMixin
from .models import ServiceRequest


class ServiceCatalogChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, service):
        return f"{service.name} — {service.category}"


class ServiceRequestForm(InlineValidationMixin, forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset())
    service = ServiceCatalogChoiceField(
        queryset=ServiceCatalog.objects.none(),
        empty_label="Select an agricultural request type",
        label="Request Type",
    )

    class Meta:
        model = ServiceRequest
        fields = ["farmer", "service", "subject", "priority", "status", "notes", "assigned_to"]
        labels = {
            "service": "Request Type",
            "assigned_to": "Assign to Staff",
            "notes": "Request Details",
        }
        widgets = {
            "subject": forms.TextInput(
                attrs={"placeholder": "Briefly describe what the farmer needs"}
            ),
            "notes": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Add useful details about the farmer's request..."}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["farmer"].queryset = active_farmer_queryset(
            self.instance.farmer_id if self.instance and self.instance.pk else None
        )
        canonical_codes = [code for code, _name, _category in CANONICAL_AGRICULTURAL_SERVICES]
        services = ServiceCatalog.objects.filter(is_active=True, code__in=canonical_codes)
        if self.instance and self.instance.pk and self.instance.service_id:
            services = ServiceCatalog.objects.filter(
                pk__in=[*services.values_list("pk", flat=True), self.instance.service_id]
            )
        self.fields["service"].queryset = services.order_by("category", "name")
        self.fields["service"].help_text = (
            "Choose the closest match. Use “Other Agricultural Concern” only when none applies."
        )
        self.fields["assigned_to"].queryset = CustomUser.objects.filter(
            role="STAFF", is_active=True
        ).order_by("first_name", "last_name", "username")
        self.fields["assigned_to"].required = False

    def clean_subject(self):
        subject = self.cleaned_data.get("subject", "").strip()
        if len(subject) < 5:
            raise forms.ValidationError("Describe the request in at least 5 characters.")
        return subject

    def clean_status(self):
        status = self.cleaned_data.get("status")
        if status == "COMPLETED" and not (
            self.instance.pk and self.instance.interventions.filter(is_active=True).exists()
        ):
            raise forms.ValidationError(
                "Record the delivered intervention while this request is In Progress; "
                "the request will then be completed automatically."
            )
        return status
