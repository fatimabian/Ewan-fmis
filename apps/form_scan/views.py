import json

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from apps.common.constants import ROSARIO_BARANGAYS, ROSARIO_COMMODITY_VALUES
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.farm_parcels.rosario_boundary import ROSARIO_BOUNDARY
from apps.farmers.models import Farmer
from apps.ocr import services as ocr
from apps.ocr.conf import ocr_setting

from .forms import ScanReviewForm, ScanUploadForm
from .models import FormScan
from .services import ScanError, approve_scan, create_scan, discard_scan, recheck
from .validation import validate

FIELD_LABELS = {
    "farmer_name": "Farmer name on the form",
    "barangay": "Barangay",
    "parcel_name": "Parcel name",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "area_hectares": "Farm area (hectares)",
    "commodity": "Commodity",
    "ownership_type": "Ownership",
}
CANDIDATE_LIMIT = 15


class ScanAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    """Only authorised staff accounts may use the scanner."""

    denied_message = "Scan & Auto-Fill is available to staff accounts only."


def farmer_candidates(scan, query):
    """Active farmers whose name matches the search box, or the name written on the form."""
    text = (query or scan.fields.get("farmer_name", "")).replace(",", " ")
    words = [word for word in text.split() if len(word) > 1]
    if not words:
        return Farmer.objects.none()
    match = Q()
    for word in words:
        match |= Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(middle_name__icontains=word)
    return Farmer.objects.filter(is_active=True).filter(match).order_by("last_name", "first_name")[:CANDIDATE_LIMIT]


class ScanUploadView(ScanAccessMixin, TemplateView):
    template_name = "form_scan/upload.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            base_template="base/staff_base.html",
            form=kwargs.get("form") or ScanUploadForm(),
            recent=FormScan.objects.filter(created_by=self.request.user)[:8],
            provider=ocr_setting("PROVIDER"),
            sample_mode=ocr_setting("PROVIDER") == "sample",
            requests_left=ocr.requests_left_today(),
        )
        return context

    def post(self, request, *args, **kwargs):
        form = ScanUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                scan = create_scan(request.user, form.cleaned_data["photo"])
            except ScanError as error:
                form.add_error("photo", str(error))
            else:
                if not scan.ocr_available:
                    messages.warning(request, "The form reader is not available right now, so the form is open for manual entry. Compare the photo and type the values.")
                return redirect("form_scan:review", pk=scan.pk)
        return self.render_to_response(self.get_context_data(form=form))


class ScanReviewView(ScanAccessMixin, TemplateView):
    template_name = "form_scan/review.html"

    def dispatch(self, request, *args, **kwargs):
        self.scan = get_object_or_404(FormScan, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def build_form(self, data=None):
        initial = {**self.scan.fields, "farmer": self.scan.farmer_id}
        form = ScanReviewForm(data, initial=initial)
        keep = [pk for pk in [(data or {}).get("farmer"), self.scan.farmer_id] if pk]
        candidates = [farmer.pk for farmer in farmer_candidates(self.scan, self.request.GET.get("q"))]
        form.fields["farmer"].queryset = Farmer.objects.filter(is_active=True, pk__in=candidates + keep).order_by("last_name", "first_name")
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get("form") or self.build_form()
        scan = self.scan
        values = (
            {name: (form.data.get(name) or "").strip() for name in scan.fields}
            if form.is_bound else scan.fields
        )
        result = validate(values, {n: e.get("confidence") for n, e in scan.ocr_fields.items()}, polygon=scan.drawn_polygon, exclude_parcel_pk=scan.parcel_id)
        threshold = ocr_setting("CONFIDENCE_THRESHOLD")
        rows = []
        for name in scan.fields:
            confidence = scan.ocr_fields.get(name, {}).get("confidence")
            rows.append({
                "field": form[name], "label": FIELD_LABELS.get(name, name),
                "confidence": None if confidence is None else round(confidence * 100),
                "low": bool(values.get(name) and confidence is not None and confidence < threshold),
            })
        context.update(
            base_template="base/staff_base.html", scan=scan, form=form, rows=rows, result=result,
            checks=[{**check.as_dict(), "fix_json": json.dumps(check.suggestion)} for check in result.checks],
            editable=scan.status == FormScan.STATUS_DRAFT, search=self.request.GET.get("q", ""),
            barangays=ROSARIO_BARANGAYS, commodities=sorted(ROSARIO_COMMODITY_VALUES),
            map_data={
                "boundary": [list(point) for point in ROSARIO_BOUNDARY],
                "point": result.point, "suggested": result.suggested_point,
                "status": result.status, "saved": scan.parcel.coordinates if scan.parcel_id else "",
            },
            threshold_percent=round(threshold * 100),
        )
        return context

    def post(self, request, *args, **kwargs):
        scan = self.scan
        if scan.status != FormScan.STATUS_DRAFT:
            messages.info(request, "This scan has already been finished.")
            return redirect("form_scan:review", pk=scan.pk)
        action = request.POST.get("action", "check")
        if action == "discard":
            discard_scan(scan, request.user)
            messages.success(request, "Scan discarded. The photo and audit trail are kept.")
            return redirect("form_scan:upload")
        form = self.build_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        values = form.values()
        if action == "approve":
            farmer = form.cleaned_data["farmer"]
            if farmer is None:
                form.add_error("farmer", "Choose the farmer this parcel belongs to.")
                return self.render_to_response(self.get_context_data(form=form))
            try:
                parcel = approve_scan(scan, request.user, values, farmer)
            except ScanError as error:
                messages.error(request, str(error))
                recheck(scan, request.user, values)
                return self.render_to_response(self.get_context_data(form=self.build_form(request.POST)))
            messages.success(request, f"Saved as {parcel.display_name} for {farmer.full_name}.")
            return redirect("form_scan:review", pk=scan.pk)
        recheck(scan, request.user, values)
        messages.info(request, "Checks updated.")
        return redirect("form_scan:review", pk=scan.pk)


class ScanImageView(ScanAccessMixin, View):
    """Serve a stored form photo to signed-in staff only; it is never public."""

    def get(self, request, pk):
        scan = get_object_or_404(FormScan, pk=pk)
        try:
            handle = scan.image.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404
        response = FileResponse(handle, content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["Content-Disposition"] = "inline"
        return response
