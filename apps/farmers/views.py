import base64
import mimetypes
from io import BytesIO

from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.common.record_history import farmer_update_rows
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel

from .forms import (
    CropRegistrationFormSet,
    DocumentRegistrationFormSet,
    FarmerProfileUpdateForm,
    FarmerRegistrationForm,
    FarmerRegistrationStatusForm,
    ParcelRegistrationFormSet,
)
from .models import Farmer, FarmerDocument
from .history import farmer_snapshot, record_farmer_update
from .rsbsa_pdf import rsbsa_pdf_response
from apps.activity_logs.services import record_request_event

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
        queryset = Farmer.objects.prefetch_related("parcels__crops")
        query = self.request.GET.get("q", "").strip()
        barangay = self.request.GET.get("barangay", "").strip()
        sex = self.request.GET.get("sex", "").strip()
        status = self.request.GET.get("status", "active").strip()
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
        queryset = queryset.filter(is_active=status == "active")
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
            "update_history__actor",
        ).select_related("last_updated_by")


class FarmerHistoryView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareTemplateMixin, DetailView
):
    model = Farmer
    template_name = "shared/record_history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "history_title": "Farmer Information Update History",
            "record_label": (
                f"{self.object.rsbsa_number or 'RSBSA ID not assigned'} · "
                f"{self.object.full_name}"
            ),
            "back_url": reverse("farmers:detail", args=[self.object.pk]),
            "edit_url": reverse("farmers:edit", args=[self.object.pk]) if self.object.is_active else "",
            "edit_label": "Update Slip A",
            "history_entries": farmer_update_rows(
                self.object.update_history.select_related("actor").all()
            ),
        })
        return context


class FarmerRSBSAExportView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def get(self, request, pk):
        farmer = get_object_or_404(
            Farmer.objects.prefetch_related("parcels__crops"),
            pk=pk,
        )
        response = rsbsa_pdf_response(farmer)
        record_request_event(
            request,
            title="RSBSA Form Exported",
            module="Reports",
            description=f"{request.user.display_name} exported one farmer's official RSBSA form.",
            target_label=farmer.rsbsa_number or farmer.full_name,
            details=[{"field": "Farmer", "after": farmer.full_name}],
        )
        return response


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
            parcel_primary_area = {}
            parcel_primary_forms = {}
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
                if crop_area and crop_form.cleaned_data.get("is_intercrop") is False:
                    parcel_primary_area[parcel_number] = (
                        parcel_primary_area.get(parcel_number, 0) + crop_area
                    )
                    parcel_primary_forms.setdefault(parcel_number, []).append(crop_form)
            for parcel_number, total_area in parcel_primary_area.items():
                parcel_area = parcel_rows[parcel_number].cleaned_data.get("area_hectares")
                if parcel_area and total_area > parcel_area:
                    for crop_form in parcel_primary_forms[parcel_number]:
                        crop_form.add_error(
                            "area_hectares",
                            (
                                f"Parcel {parcel_number}'s active non-intercrop crops total "
                                f"{total_area} ha, exceeding its {parcel_area} ha area."
                            ),
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
            # Encoding creates the operational record, but the official RSBSA ID
            # is assigned manually only after the office completes its workflow.
            farmer.registration_status = "ENCODED"
            farmer.rsbsa_number = None
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
                    if field_name not in {
                        "parcel_number",
                        "other_crop_name",
                        "cropping_start_month",
                        "cropping_end_month",
                        "DELETE",
                    }:
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
        farmer = get_object_or_404(
            Farmer,
            pk=pk,
            is_active=True,
            registration_status="COMPLETED",
            rsbsa_number__isnull=False,
        )
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
            registration_status="COMPLETED",
            rsbsa_number__isnull=False,
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


class FarmerRegistrationStatusUpdateView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareTemplateMixin, UpdateView
):
    model = Farmer
    form_class = FarmerRegistrationStatusForm
    template_name = "farmers/registration_status_form.html"

    def get_queryset(self):
        return Farmer.objects.filter(is_active=True)

    def get_success_url(self):
        return reverse("farmers:detail", args=[self.object.pk])

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.snapshot_before_update = farmer_snapshot(self.object)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if not form.has_changed():
            messages.info(self.request, "No registration status changes were made.")
            return redirect(self.get_success_url())

        before = self.snapshot_before_update
        with transaction.atomic():
            response = super().form_valid(form)
            record_farmer_update(
                farmer=self.object,
                actor=self.request.user,
                update_type="STATUS",
                before=before,
                change_reason="OTHER",
                remarks="Office-controlled registration processing update.",
            )
        messages.success(self.request, "The registration status was updated.")
        return response


class FarmerSlipBUpdateView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Keep old Slip B links useful while routing updates to parcel management."""

    def get(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        parcel = farmer.parcels.filter(is_active=True).order_by("pk").first()
        if parcel:
            return redirect("farm_parcels:edit", pk=parcel.pk)
        return redirect(f"{reverse('farm_parcels:create')}?farmer={farmer.pk}")

    post = get


class FarmerDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive the shared record so dependent module data remains intact."""

    def post(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk)
        restoring = request.POST.get("action") == "restore"
        farmer.is_active = restoring
        farmer.save(update_fields=["is_active"])
        action = "Restored" if restoring else "Archived"
        record_request_event(
            request,
            title=f"Farmer Record {action}",
            module="Farmers",
            description=(
                f"{request.user.display_name} {action.casefold()} a farmer record without "
                "deleting related data."
            ),
            target_label=farmer.full_name,
        )
        messages.success(
            request,
            (
                f"{farmer.full_name} was restored to active records."
                if restoring
                else f"{farmer.full_name} was archived. Find the record under Record Status → Archived; related farm records were preserved."
            ),
        )
        return redirect("farmers:list")


class FarmerDocumentDownloadView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Serve identity/supporting documents only after an authorized staff check."""

    def get(self, request, pk):
        document = get_object_or_404(
            FarmerDocument.objects.select_related("farmer"),
            pk=pk,
            farmer__is_active=True,
        )
        if not document.file_available:
            messages.warning(
                request,
                "This supporting document file is no longer available. Upload a replacement from Update Slip A.",
            )
            record_request_event(
                request,
                title="Supporting Document Unavailable",
                module="Farmers",
                description=(
                    f"{request.user.display_name} attempted to open a supporting document "
                    "whose stored file is missing."
                ),
                status="Warning",
                target_label=document.farmer.full_name,
            )
            return redirect("farmers:detail", pk=document.farmer_id)
        content_type = mimetypes.guess_type(document.file.name)[0] or "application/octet-stream"
        try:
            file_handle = document.file.open("rb")
        except (FileNotFoundError, OSError):
            messages.warning(
                request,
                "This supporting document could not be opened. Upload a replacement from Update Slip A.",
            )
            return redirect("farmers:detail", pk=document.farmer_id)
        response = FileResponse(file_handle, content_type=content_type)
        response["Content-Disposition"] = f'inline; filename="supporting-document-{document.pk}"'
        response["X-Content-Type-Options"] = "nosniff"
        record_request_event(
            request,
            title="Supporting Document Accessed",
            module="Farmers",
            description=f"{request.user.display_name} opened a protected supporting document.",
            target_label=document.farmer.full_name,
        )
        return response
