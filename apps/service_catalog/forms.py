from django import forms
from django.forms import ModelForm
from apps.common.forms import InlineValidationMixin
from .models import ServiceCatalog


class ServiceCatalogForm(InlineValidationMixin, ModelForm):
    CATEGORY_CHOICES = [
        ("", "Select a service category"),
        ("Agricultural Testing", "Agricultural Testing"),
        ("Crop Production Support", "Crop Production Support"),
        ("Livestock and Poultry", "Livestock and Poultry"),
        ("Farm Mechanization", "Farm Mechanization"),
        ("Irrigation and Water", "Irrigation and Water"),
        ("Pest and Disease Management", "Pest and Disease Management"),
        ("Training and Extension", "Training and Extension"),
        ("Registration and Certification", "Registration and Certification"),
        ("Input Assistance", "Input Assistance"),
        ("Market and Livelihood Support", "Market and Livelihood Support"),
        ("Other", "Other"),
    ]
    COLOR_CHOICES = [
        ("#008552", "Green"),
        ("#2563eb", "Blue"),
        ("#7c3aed", "Purple"),
        ("#ea580c", "Orange"),
        ("#eab308", "Yellow"),
        ("#e11d48", "Red"),
        ("#64748b", "Gray"),
    ]
    SERVICE_TYPE_CHOICES = [
        ("", "Select service type"),
        ("Technical Assistance", "Technical Assistance"),
        ("Input Assistance", "Input Assistance"),
        ("Training or Seminar", "Training or Seminar"),
        ("Registration or Certification", "Registration or Certification"),
        ("Laboratory or Testing", "Laboratory or Testing"),
        ("Equipment or Infrastructure Support", "Equipment or Infrastructure Support"),
        ("Advisory or Information", "Advisory or Information"),
        ("Other Agricultural Service", "Other Agricultural Service"),
    ]
    BENEFICIARY_CHOICES = [
        ("Farmers", "Farmers"),
        ("Fisherfolk", "Fisherfolk"),
        ("Livestock and Poultry Raisers", "Livestock and Poultry Raisers"),
        ("Cooperatives and Farmer Associations", "Cooperatives and Farmer Associations"),
        ("Agrarian Reform Beneficiaries", "Agrarian Reform Beneficiaries"),
        ("Women and Youth in Agriculture", "Women and Youth in Agriculture"),
    ]
    PROCESSING_TIME_CHOICES = [
        ("", "Select estimated processing time"),
        ("Same working day", "Same working day"),
        ("1-2 working days", "1-2 working days"),
        ("3-5 working days", "3-5 working days"),
        ("1-2 weeks", "1-2 weeks"),
        ("Schedule-based", "Schedule-based"),
        ("Depends on field assessment", "Depends on field assessment"),
    ]
    AVAILABILITY_CHOICES = [
        ("", "Select when the service is offered"),
        ("Year-round", "Year-round"),
        ("On request", "On request"),
        ("Scheduled dates", "Scheduled dates"),
        ("Limited slots", "Limited slots"),
    ]
    SEASONALITY_CHOICES = [
        ("Not seasonal / N/A", "Not seasonal / N/A"),
        ("Wet season", "Wet season"),
        ("Dry season", "Dry season"),
        ("Wet and dry seasons", "Wet and dry seasons"),
        ("Depends on crop cycle", "Depends on crop cycle"),
    ]
    REQUIREMENT_CHOICES = [
        ("None", "No documents required"),
        ("Valid government-issued ID", "Valid government-issued ID"),
        ("RSBSA farmer record or reference number", "RSBSA farmer record or reference number"),
        ("Proof of residence", "Proof of residence"),
        ("Proof of land ownership or tenure", "Proof of land ownership or tenure"),
        ("Barangay certification", "Barangay certification"),
        ("Request letter", "Request letter"),
        ("Photos or supporting evidence", "Photos or supporting evidence"),
    ]

    category = forms.ChoiceField(choices=CATEGORY_CHOICES)
    icon_name = forms.ChoiceField(choices=ServiceCatalog.ICON_CHOICES, widget=forms.RadioSelect)
    badge_color = forms.ChoiceField(choices=COLOR_CHOICES, widget=forms.RadioSelect)
    service_type = forms.ChoiceField(choices=SERVICE_TYPE_CHOICES)
    target_beneficiaries = forms.MultipleChoiceField(choices=BENEFICIARY_CHOICES, widget=forms.CheckboxSelectMultiple)
    processing_time = forms.ChoiceField(choices=PROCESSING_TIME_CHOICES)
    availability = forms.ChoiceField(choices=AVAILABILITY_CHOICES)
    seasonality = forms.ChoiceField(choices=SEASONALITY_CHOICES, initial="Not seasonal / N/A")
    requirements = forms.MultipleChoiceField(choices=REQUIREMENT_CHOICES, widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].widget.attrs.update({"readonly": True, "placeholder": "Auto-generated"})
        self.fields["description"].widget.attrs.update({"placeholder": "Enter a short description of the service..."})
        if self.instance and self.instance.pk:
            self.initial["target_beneficiaries"] = self._selected_values(
                self.instance.target_beneficiaries, self.BENEFICIARY_CHOICES
            )
            self.initial["requirements"] = self._selected_values(
                self.instance.requirements, self.REQUIREMENT_CHOICES
            )

    @staticmethod
    def _selected_values(stored_value, choices):
        selected = {part.strip() for part in (stored_value or "").replace("\n", ",").split(",") if part.strip()}
        return [value for value, _label in choices if value in selected]

    def clean_target_beneficiaries(self):
        return ", ".join(self.cleaned_data["target_beneficiaries"])

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        duplicate = ServiceCatalog.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if name and duplicate.exists():
            raise forms.ValidationError("A service catalog item with this name already exists.")
        return name

    def clean_requirements(self):
        values = self.cleaned_data["requirements"]
        if "None" in values and len(values) > 1:
            raise forms.ValidationError("Choose either 'No documents required' or the required documents, not both.")
        if "None" in values:
            return "None"
        return ", ".join(values)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.office_responsible = "Office for Agricultural Services"
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    class Meta:
        model = ServiceCatalog
        fields = ["name", "code", "category", "description", "service_type", "target_beneficiaries", "processing_time", "availability", "seasonality", "requirements", "icon_name", "badge_color"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "requirements": forms.Textarea(attrs={"rows": 4})}
