from django import forms

from apps.authentication.models import CustomUser
from apps.common.forms import InlineValidationMixin
from .models import WeatherCoverageArea, WeatherMonitoringRule


class WeatherCoverageAreaForm(InlineValidationMixin, forms.ModelForm):
    class Meta:
        model = WeatherCoverageArea
        fields = ("code", "name", "latitude", "longitude", "radius_km", "is_active")


class WeatherMonitoringRuleForm(InlineValidationMixin, forms.ModelForm):
    class Meta:
        model = WeatherMonitoringRule
        fields = (
            "name", "coverage_area", "minimum_daily_rainfall_mm",
            "consecutive_days", "accumulated_rainfall_mm", "suggested_priority",
            "cooldown_days", "recommended_action", "is_approved", "is_active",
        )


class WeatherEventReviewForm(InlineValidationMixin, forms.Form):
    action = forms.ChoiceField(choices=(("approve", "Approve"), ("dismiss", "Dismiss")))
    assigned_to = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(), required=False, label="Assign to staff"
    )
    scheduled_for = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = CustomUser.objects.filter(
            role="STAFF", is_active=True, deleted_at__isnull=True
        ).order_by("first_name", "last_name", "username")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "approve" and not cleaned.get("assigned_to"):
            self.add_error("assigned_to", "Assign a staff member before approval.")
        if cleaned.get("action") == "dismiss" and not (cleaned.get("reason") or "").strip():
            self.add_error("reason", "Record why this preliminary weather event is dismissed.")
        return cleaned
