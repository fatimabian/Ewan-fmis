import base64
from io import BytesIO

from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel

from .forms import (
    CropRegistrationFormSet,
    DocumentRegistrationFormSet,
    FarmerProfileUpdateForm,
    FarmerRegistrationForm,
    FarmerSlipBLivelihoodForm,
    ParcelRegistrationFormSet,
)
from .models import Farmer, FarmerDocument, FarmerUpdateHistory
from .history import farmer_snapshot, record_farmer_update

FARMER_QR_SALT = "fmis.farmers.field-record.v1"


def build_farmer_qr_token(farmer_id):
    """Create a permanent, tamper-resistant identifier for a printed field QR."""
    return signing.dumps(
        {"farmer_id": farmer_id, "purpose": "field-record"},
        salt=FARMER_QR_SALT,
        compress=True,
    )


def build_qr_data_uri(value):
    """Render the signed field-record link without relying on a public QR service."""
    try:
        import qrcode
    except ImportError:
        return ""

    qr_code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr_code.add_data(value)
    qr_code.make(fit=True)
    image = qr_code.make_image(fill_color="#102a1f", back_color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def farmer_qr_context(request, farmer):
    token = build_farmer_qr_token(farmer.pk)
    secure_url = request.build_absolute_uri(reverse("farmers:qr_access", args=[token]))
    return {
        "farmer": farmer,
        "secure_url": secure_url,
        "qr_data_uri": build_qr_data_uri(secure_url),
    }


class RoleAwareTemplateMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class FarmerListView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareTemplateMixin, ListView):
    model = Farmer
    template_name = "farmers/list.html"
    paginate_by = 10

    def get_queryset(self):
        latest_update = FarmerUpdateHistory.objects.select_related("actor").order_by(
            "-created_at", "-pk"
        )[:1]
        queryset = Farmer.objects.select_related("last_updated_by").prefetch_related(
            "parcels__crops",
            Prefetch(
                "update_history",
                queryset=latest_update,
                to_attr="latest_update_for_list",
            ),
        )
        query = self.request.GET.get("q", "").strip()
        barangay = self.request.GET.get("barangay", "").strip()
        sex = self.request.GET.get("sex", "").strip()
        if query:
            farmer_id = query.upper().removeprefix("F-")
            filters = (
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(rsbsa_number__icontains=query)
            )
            if farmer_id.isdigit():
                filters |= Q(pk=int(farmer_id))
            queryset = queryset.filter(filters)
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if sex in {"MALE", "FEMALE"}:
            queryset = queryset.filter(sex=sex)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barangays"] = (
            Farmer.objects.values_list("barangay", flat=True).distinct().order_by("barangay")
        )
        return context


class FarmerDetailView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareTemplateMixin, DetailView
):
    model = Farmer
    template_name = "farmers/detail.html"

    def get_queryset(self):
        return Farmer.objects.prefetch_related(
            "documents",
            "parcels__crops",
            "service_requests__service",
            "update_history__actor",
        ).select_related("last_updated_by")


class FarmerRegistrationView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    template_name = "farmers/registration.html"

    def build_context(self, profile_form, parcel_formset, crop_formset, document_formset):
        return {
            "base_template": (
                "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
            ),
            "profile_form": profile_form,
            "parcel_formset": parcel_formset,
            "crop_formset": crop_formset,
            "document_formset": document_formset,
        }

    def get(self, request):
        return render(
            request,
            self.template_name,
            self.build_context(
                FarmerRegistrationForm(),
                ParcelRegistrationFormSet(prefix="parcels"),
                CropRegistrationFormSet(prefix="crops"),
                DocumentRegistrationFormSet(prefix="documents"),
            ),
        )

    def post(self, request):
        profile_form = FarmerRegistrationForm(request.POST, request.FILES)
        parcel_formset = ParcelRegistrationFormSet(request.POST, prefix="parcels")
        crop_formset = CropRegistrationFormSet(request.POST, request.FILES, prefix="crops")
        document_formset = DocumentRegistrationFormSet(
            request.POST, request.FILES, prefix="documents"
        )
        forms_valid = all(
            [
                profile_form.is_valid(),
                parcel_formset.is_valid(),
                crop_formset.is_valid(),
                document_formset.is_valid(),
            ]
        )

        parcel_rows = {}
        if parcel_formset.is_valid():
            for row_number, parcel_form in enumerate(parcel_formset.forms, start=1):
                if parcel_form.cleaned_data and not parcel_form.cleaned_data.get("DELETE"):
                    parcel_rows[row_number] = parcel_form

        if crop_formset.is_valid():
            for crop_form in crop_formset.forms:
                if (
                    not crop_form.cleaned_data
                    or crop_form.cleaned_data.get("DELETE")
                ):
                    continue
                parcel_number = crop_form.cleaned_data.get("parcel_number")
                if parcel_number not in parcel_rows:
                    crop_form.add_error(
                        "parcel_number", "Choose the number of an active parcel row from Step 2."
                    )
                    forms_valid = False
                    continue
                parcel_area = parcel_rows[parcel_number].cleaned_data.get("area_hectares")
                crop_area = crop_form.cleaned_data.get("area_hectares")
                if parcel_area and crop_area and crop_area > parcel_area:
                    crop_form.add_error(
                        "area_hectares",
                        f"This cannot exceed Parcel {parcel_number}'s area of {parcel_area} ha.",
                    )
                    forms_valid = False

        if not forms_valid:
            return render(
                request,
                self.template_name,
                self.build_context(profile_form, parcel_formset, crop_formset, document_formset),
            )

        with transaction.atomic():
            farmer = profile_form.save(commit=False)
            # FMIS is the office's farmer information database. A completed
            # registration is available immediately; it is not an approval queue.
            farmer.registration_status = "APPROVED"
            farmer.submitted_at = timezone.now()
            farmer.save()

            saved_parcels = {}
            for row_number, parcel_form in parcel_rows.items():
                parcel = FarmParcel(farmer=farmer)
                for field_name, value in parcel_form.cleaned_data.items():
                    if field_name != "DELETE":
                        setattr(parcel, field_name, value)
                parcel.save()
                saved_parcels[row_number] = parcel

            for crop_form in crop_formset.forms:
                if (
                    not crop_form.cleaned_data
                    or crop_form.cleaned_data.get("DELETE")
                ):
                    continue
                crop = CropRecord(parcel=saved_parcels[crop_form.cleaned_data["parcel_number"]])
                for field_name, value in crop_form.cleaned_data.items():
                    if field_name not in {"parcel_number", "other_crop_name", "DELETE"}:
                        setattr(crop, field_name, value)
                crop.save()

            for document_form in document_formset.forms:
                if not document_form.cleaned_data or document_form.cleaned_data.get("DELETE"):
                    continue
                FarmerDocument.objects.create(
                    farmer=farmer,
                    document_type=document_form.cleaned_data["document_type"],
                    description=document_form.cleaned_data.get("description", ""),
                    file=document_form.cleaned_data["file"],
                )

        return redirect("farmers:registration_complete", pk=farmer.pk)


class FarmerRegistrationCompleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        context = {
            "base_template": (
                "base/admin_base.html" if request.user.is_admin else "base/staff_base.html"
            ),
            **farmer_qr_context(request, farmer),
        }
        return render(request, "farmers/registration_complete.html", context)


class FarmerQRPrintView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Show the printable QR card to authenticated operational staff only."""

    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk, is_active=True)
        context = {
            "base_template": "base/staff_base.html",
            **farmer_qr_context(request, farmer),
        }
        return render(request, "farmers/qr_print.html", context)


class FarmerSecureQRDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Resolve a signed QR only after staff authentication and authorization."""

    def get(self, request, token):
        try:
            payload = signing.loads(token, salt=FARMER_QR_SALT)
        except signing.BadSignature:
            messages.error(request, "This farmer QR code is invalid or has been altered.")
            return redirect("farmers:list")

        if not isinstance(payload, dict) or payload.get("purpose") != "field-record":
            messages.error(request, "This QR code is not a farmer field record.")
            return redirect("farmers:list")

        farmer = get_object_or_404(
            Farmer.objects.prefetch_related("parcels__crops"),
            pk=payload.get("farmer_id"),
            is_active=True,
        )
        return render(
            request,
            "farmers/secure_field_record.html",
            {
                "base_template": "base/staff_base.html",
                "farmer": farmer,
            },
        )


class FarmerUpdateView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareTemplateMixin, UpdateView
):
    model = Farmer
    form_class = FarmerProfileUpdateForm
    template_name = "farmers/form.html"
    def get_success_url(self):
        return reverse("farmers:detail", args=[self.object.pk])

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.snapshot_before_update = farmer_snapshot(self.object)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        before = self.snapshot_before_update
        with transaction.atomic():
            response = super().form_valid(form)
            record_farmer_update(
                farmer=self.object,
                actor=self.request.user,
                update_type="SLIP_A",
                before=before,
                transaction_code=form.cleaned_data["transaction_code"],
                change_reason=form.cleaned_data["change_reason"],
                remarks=form.cleaned_data.get("update_remarks", ""),
                date_signed=form.cleaned_data.get("date_signed"),
                date_received=form.cleaned_data.get("date_received"),
                agriculturist_name=form.cleaned_data.get("agriculturist_name", ""),
            )
        messages.success(self.request, "The farmer's RSBSA profile information was updated.")
        return response


class FarmerSlipBUpdateView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    template_name = "farmers/slip_b.html"

    def get_farmer(self, pk):
        return get_object_or_404(
            Farmer.objects.prefetch_related("parcels__crops"),
            pk=pk,
        )

    def context(self, farmer, form):
        return {
            "base_template": (
                "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
            ),
            "farmer": farmer,
            "form": form,
        }

    def get(self, request, pk):
        farmer = self.get_farmer(pk)
        return render(request, self.template_name, self.context(farmer, FarmerSlipBLivelihoodForm(instance=farmer)))

    def post(self, request, pk):
        farmer = self.get_farmer(pk)
        before = farmer_snapshot(farmer)
        form = FarmerSlipBLivelihoodForm(request.POST, instance=farmer)
        if not form.is_valid():
            return render(request, self.template_name, self.context(farmer, form))
        with transaction.atomic():
            form.save()
            record_farmer_update(
                farmer=farmer,
                actor=request.user,
                update_type="SLIP_B",
                before=before,
                transaction_code=form.cleaned_data["transaction_code"],
                change_reason=form.cleaned_data["change_reason"],
                remarks=form.cleaned_data.get("update_remarks", ""),
                date_signed=form.cleaned_data.get("date_signed"),
                date_received=form.cleaned_data.get("date_received"),
                agriculturist_name=form.cleaned_data.get("agriculturist_name", ""),
            )
        messages.success(request, "Slip B livelihood information and update history were saved.")
        return redirect("farmers:detail", pk=farmer.pk)


class FarmerDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive the shared record so dependent module data remains intact."""

    def post(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        farmer.is_active = False
        farmer.save(update_fields=["is_active"])
        messages.success(
            request, f"{farmer.full_name} was archived. Related farm records were preserved."
        )
        return redirect("farmers:list")
