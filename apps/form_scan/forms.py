from django import forms

from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer


class ScanUploadForm(forms.Form):
    """Photo upload; type and size are checked by content in the service layer."""

    photo = forms.FileField(
        label="Photo of the farmer form",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "capture": "environment"}),
    )


class ScanReviewForm(forms.Form):
    """The editable values on the review screen."""

    farmer = forms.ModelChoiceField(queryset=Farmer.objects.filter(is_active=True), required=False, empty_label="Choose the farmer")
    farmer_name = forms.CharField(required=False, max_length=250, label="Name on the form")
    barangay = forms.CharField(required=False, max_length=250)
    parcel_name = forms.CharField(required=False, max_length=250)
    latitude = forms.CharField(required=False, max_length=250)
    longitude = forms.CharField(required=False, max_length=250)
    area_hectares = forms.CharField(required=False, max_length=250, label="Farm area (ha)")
    commodity = forms.CharField(required=False, max_length=250)
    ownership_type = forms.ChoiceField(required=False, choices=[("", "Choose")] + list(FarmParcel.OWNERSHIP_CHOICES))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("autocomplete", "off")
        self.fields["barangay"].widget.attrs["list"] = "barangayList"
        self.fields["commodity"].widget.attrs["list"] = "commodityList"

    def values(self):
        """Cleaned text values without the farmer choice."""
        return {name: (value or "").strip() for name, value in self.cleaned_data.items() if name != "farmer"}
