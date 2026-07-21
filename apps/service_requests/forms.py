from django import forms
from django.db.models import Q

from apps.authentication.models import CustomUser
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
        empty_label="Select a request type from the Service Catalog",
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
            "subject": forms.TextInput(attrs={"placeholder": "Briefly describe what the farmer needs"}),
            "notes": forms.Textarea(attrs={"rows": 5, "placeholder": "Add useful details about the farmer's request..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        service_filters = Q(is_active=True)
        if self.instance and self.instance.pk:
            service_filters |= Q(pk=self.instance.service_id)
        self.fields["farmer"].queryset = active_farmer_queryset(self.instance.farmer_id if self.instance and self.instance.pk else None)
        self.fields["service"].queryset = ServiceCatalog.objects.filter(service_filters).order_by("category", "name")
        if not self.fields["service"].queryset.exists():
            self.fields["service"].help_text = "No active services are available. Ask an administrator to publish a Service Catalog item."
        self.fields["assigned_to"].queryset = CustomUser.objects.filter(role="STAFF", is_active=True).order_by("first_name", "last_name", "username")
        self.fields["assigned_to"].required = False

    def clean_subject(self):
        subject = self.cleaned_data.get("subject", "").strip()
        if len(subject) < 5:
            raise forms.ValidationError("Describe the request in at least 5 characters.")
        return subject
