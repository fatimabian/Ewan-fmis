import json

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
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
from .services import ScanError, confirm_scan, create_scan, discard_scan, recheck
from .validation import validate

FIELD_LABELS = {
    "farmer_name": "Farmer name on the form",
    "barangay": "Barangay",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "area_hectares": "Farm area (hectares)",
    "commodity": "Commodity",
    "ownership_type": "Ownership",
}
CANDIDATE_LIMIT = 15
CANDIDATE_POOL = 300


class ScanAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    """Only authorised staff accounts may use the scanner."""

    denied_message = "Scan & Auto-Fill is available to staff accounts only."


def farmer_candidates(scan, query):
    """Active farmers matching the search box or the name on the form, best matches first."""
    text = (query or scan.fields.get("farmer_name", "")).replace(",", " ")
    words = [word.casefold() for word in text.split() if len(word) > 1]
    if not words:
        return []
    match = Q()
    for word in words:
        match |= Q(first_name__icontains=word) | Q(last_name__icontains=word) | Q(middle_name__icontains=word)
    found = list(Farmer.objects.filter(is_active=True).filter(match).order_by("last_name", "first_name")[:CANDIDATE_POOL])

    def score(farmer):
        name = f"{farmer.first_name} {farmer.middle_name} {farmer.last_name}".casefold()
        return -sum(word in name for word in words)

    return sorted(found, key=score)[:CANDIDATE_LIMIT]


def farmer_query(farmer_id):
    """Carry an already chosen farmer through the scan as an id only (no names in URLs)."""
    return f"?farmer={farmer_id}" if str(farmer_id).isdigit() else ""


class ScanUploadView(ScanAccessMixin, TemplateView):
    template_name = "form_scan/upload.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            base_template="base/staff_base.html",
            form=kwargs.get("form") or ScanUploadForm(initial={"target": self.request.GET.get("target", FormScan.TARGET_PARCEL), "farmer": self.request.GET.get("farmer", "")}),
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
                scan = create_scan(request.user, form.cleaned_data["photo"], form.cleaned_data["target"])
            except ScanError as error:
                form.add_error("photo", str(error))
            else:
                if not scan.ocr_available:
                    messages.warning(request, "The form reader is not available right now, so the form is open for manual entry. Compare the photo and type the values.")
                return redirect(f"{reverse('form_scan:review', args=[scan.pk])}{farmer_query(form.cleaned_data['farmer'])}")
        return self.render_to_response(self.get_context_data(form=form))


class ScanReviewView(ScanAccessMixin, TemplateView):
    template_name = "form_scan/review.html"

    def dispatch(self, request, *args, **kwargs):
        self.scan = get_object_or_404(FormScan, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def continue_url(self):
        """The form that receives the confirmed values."""
        if self.scan.target == FormScan.TARGET_CROP:
            base, farmer = reverse("crops:create"), self.scan.farmer_id
        else:
            base, farmer = reverse("farm_parcels:create"), self.scan.farmer_id
        query = f"?scan={self.scan.pk}" + (f"&farmer={farmer}" if farmer else "")
        return base + query

    def build_form(self, data=None):
        preset = self.request.GET.get("farmer", "")
        initial = {**self.scan.fields, "farmer": self.scan.farmer_id or (preset if preset.isdigit() else None)}
        form = ScanReviewForm(data, initial=initial)
        keep = [pk for pk in [(data or {}).get("farmer"), self.scan.farmer_id] if pk]
        ranked = [farmer.pk for farmer in farmer_candidates(self.scan, self.request.GET.get("q"))]
        choices = Farmer.objects.filter(is_active=True, pk__in=ranked + keep)
        order = {pk: position for position, pk in enumerate(ranked)}
        form.fields["farmer"].queryset = choices
        form.fields["farmer"].choices = [("", "Choose the farmer")] + [
            (farmer.pk, f"{farmer.full_name} · {farmer.barangay}")
            for farmer in sorted(choices, key=lambda farmer: order.get(farmer.pk, -1))
        ]
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
            editable=scan.status in (FormScan.STATUS_DRAFT, FormScan.STATUS_CONFIRMED),
            continue_url=self.continue_url(), search=self.request.GET.get("q", ""),
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
        here = f"{reverse('form_scan:review', args=[scan.pk])}" + (f"?{request.GET.urlencode()}" if request.GET else "")
        if scan.status not in (FormScan.STATUS_DRAFT, FormScan.STATUS_CONFIRMED):
            messages.info(request, "This scan has already been finished.")
            return redirect(here)
        action = request.POST.get("action", "check")
        if action == "discard":
            discard_scan(scan, request.user)
            messages.success(request, "Scan discarded. The photo and audit trail are kept.")
            return redirect("dashboard:staff_home")
        form = self.build_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        values = form.values()
        if action == "confirm":
            try:
                self.scan = confirm_scan(scan, request.user, values, form.cleaned_data["farmer"])
            except ScanError as error:
                messages.error(request, str(error))
                recheck(scan, request.user, values)
                return self.render_to_response(self.get_context_data(form=self.build_form(request.POST)))
            messages.success(request, "Values confirmed and entered in the form below. Check them against the photo, then save.")
            return redirect(self.continue_url())
        recheck(scan, request.user, values)
        messages.info(request, "Checks updated.")
        return redirect(here)


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
