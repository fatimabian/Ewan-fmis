"""Lets the Add Farm Parcel and Add Commodity forms open pre-filled from a confirmed scan."""
from apps.farm_parcels.coordinate_services import parse_coordinates

from .models import FormScan
from .services import blocking_problem, finalize_scan


class ScanPrefillMixin:
    """Add to a CreateView: confirmed scan values pre-fill the form and are audited when it saves."""

    scan_target = FormScan.TARGET_PARCEL
    _scan_cache = None

    def get_scan(self):
        """The confirmed scan this request refers to, or None (also for other staff's scans)."""
        if self._scan_cache is None:
            raw = self.request.POST.get("scan") or self.request.GET.get("scan") or ""
            scan = None
            if raw.isdigit():
                scan = FormScan.objects.filter(
                    pk=raw, status=FormScan.STATUS_CONFIRMED, target=self.scan_target
                ).first()
            self._scan_cache = scan or False
        return self._scan_cache or None

    def get_initial(self):
        initial = super().get_initial()
        scan = self.get_scan()
        if scan and self.request.method == "GET":
            initial.update({key: value for key, value in scan.prefill.items() if value != ""})
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["scan"] = self.get_scan()
        context["scan_target"] = self.scan_target
        context["scan_farmer"] = self.request.GET.get("farmer", "")
        return context

    def scan_values(self, form):
        """The about-to-be-saved values in the scan's own vocabulary."""
        data = form.cleaned_data
        point = parse_coordinates(data.get("coordinates", ""))
        return {
            "barangay": data.get("barangay", ""), "area_hectares": str(data.get("area_hectares") or ""),
            "latitude": f"{point[0]:.6f}" if point else "", "longitude": f"{point[1]:.6f}" if point else "",
        }

    def form_valid(self, form):
        scan = self.get_scan()
        if scan and self.scan_target == FormScan.TARGET_PARCEL:
            problem = blocking_problem(scan, self.scan_values(form))
            if problem:
                form.add_error("coordinates", problem)
                return self.form_invalid(form)
        response = super().form_valid(form)
        if scan:
            finalize_scan(scan, self.request.user, self.object)
        return response
