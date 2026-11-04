"""Official-form printing with bounded, explicit printer calibration settings."""
from urllib.parse import urlencode

from django import forms
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from apps.activity_logs.services import record_request_event
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from .models import Farmer
from .rsbsa_pdf import rsbsa_pdf_response


class RSBSAAlignmentForm(forms.Form):
    mode = forms.ChoiceField(label="Print on", choices=(("complete", "Blank paper — include the official form"), ("text", "Preprinted RSBSA form — values only")))
    offset_x = forms.DecimalField(label="Move right (+) / left (−), mm", min_value=-15, max_value=15, decimal_places=1, widget=forms.NumberInput(attrs={"step": "0.5"}))
    offset_y = forms.DecimalField(label="Move down (+) / up (−), mm", min_value=-15, max_value=15, decimal_places=1, widget=forms.NumberInput(attrs={"step": "0.5"}))
    scale = forms.DecimalField(label="Text scale (%)", min_value=95, max_value=105, decimal_places=2, widget=forms.NumberInput(attrs={"step": "0.25"}))

    @classmethod
    def from_query(cls, query):
        return cls({**{"mode": "complete", "offset_x": "0", "offset_y": "0", "scale": "100"}, **query.dict()})


class FarmerRSBSAPrintView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        form = RSBSAAlignmentForm.from_query(request.GET)
        preview_url = None
        if form.is_valid():
            preview_url = reverse("farmers:rsbsa_form_pdf", args=[farmer.pk]) + "?" + urlencode(form.cleaned_data)
        return render(request, "farmers/rsbsa_print.html", {"farmer": farmer, "alignment_form": form, "preview_url": preview_url})


class FarmerRSBSAFormPDFView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        form = RSBSAAlignmentForm.from_query(request.GET)
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid print settings. Open Print RSBSA Form and check the alignment values.")
        response = rsbsa_pdf_response(farmer, download=request.GET.get("download") == "1", **form.cleaned_data)
        record_request_event(request, title="RSBSA Form Prepared for Printing", module="Reports", description=f"{request.user.display_name} prepared the official RSBSA form for {farmer.record_id}.", target_label=farmer.record_id)
        return response
