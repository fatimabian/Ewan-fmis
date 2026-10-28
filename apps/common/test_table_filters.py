from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest


class TableToolbarFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = CustomUser.objects.create_user(
            username="toolbar-staff", password="Valid-pass-123!", role="STAFF"
        )
        cls.admin = CustomUser.objects.create_user(
            username="toolbar-admin", password="Valid-pass-123!", role="ADMIN"
        )
        cls.old_farmer = Farmer.objects.create(
            first_name="Older", last_name="Farmer", barangay="Alupay"
        )
        cls.new_farmer = Farmer.objects.create(
            first_name="Newer", last_name="Farmer", barangay="Bulihan"
        )
        cls.old_parcel = FarmParcel.objects.create(
            farmer=cls.old_farmer,
            barangay="Alupay",
            area_hectares=Decimal("1.00"),
            ownership_type="OWNED",
            land_type="UPLAND",
        )
        cls.new_parcel = FarmParcel.objects.create(
            farmer=cls.new_farmer,
            barangay="Bulihan",
            area_hectares=Decimal("2.00"),
            ownership_type="TENANT",
            land_type="LOWLAND",
        )
        cls.old_crop = CropRecord.objects.create(
            parcel=cls.old_parcel, crop_type="Rice", planting_date=date(2026, 1, 1)
        )
        cls.new_crop = CropRecord.objects.create(
            parcel=cls.new_parcel, crop_type="Corn", planting_date=date(2026, 2, 2)
        )
        service = ServiceCatalog.objects.create(
            code="TOOLBAR-TEST",
            name="Toolbar Test Service",
            category="Testing",
            description="Filter regression fixture",
            processing_time="One day",
        )
        cls.old_request = ServiceRequest.objects.create(
            farmer=cls.old_farmer, service=service, status="PENDING"
        )
        cls.new_request = ServiceRequest.objects.create(
            farmer=cls.new_farmer, service=service, status="PENDING"
        )
        cls.old_intervention = Intervention.objects.create(
            farmer=cls.old_farmer,
            status="COMPLETED",
            intervention_type="SEEDS",
            intervention_date=date(2026, 1, 1),
        )
        cls.new_intervention = Intervention.objects.create(
            farmer=cls.new_farmer,
            status="COMPLETED",
            intervention_type="TRAINING",
            intervention_date=date(2026, 2, 2),
        )
        cls.old_activity = ActivityLog.objects.create(
            actor=cls.admin, action="old", path="/old", title="Older activity"
        )
        cls.new_activity = ActivityLog.objects.create(
            actor=cls.admin, action="new", path="/new", title="Newer activity"
        )
        old_timestamp = timezone.make_aware(datetime(2026, 1, 1, 9, 0))
        new_timestamp = timezone.make_aware(datetime(2026, 2, 2, 9, 0))
        for model, old_pk, new_pk in (
            (Farmer, cls.old_farmer.pk, cls.new_farmer.pk),
            (FarmParcel, cls.old_parcel.pk, cls.new_parcel.pk),
            (ServiceRequest, cls.old_request.pk, cls.new_request.pk),
            (ActivityLog, cls.old_activity.pk, cls.new_activity.pk),
        ):
            model.objects.filter(pk=old_pk).update(created_at=old_timestamp)
            model.objects.filter(pk=new_pk).update(created_at=new_timestamp)

    def test_staff_management_pages_use_compact_filter_toolbar(self):
        self.client.force_login(self.staff)
        for url_name, filter_id in (
            ("farmers:list", "farmerFilters"),
            ("farm_parcels:list", "parcelFilters"),
            ("crops:list", "commodityFilters"),
            ("service_requests:list", "requestFilters"),
            ("interventions:list", "interventionFilters"),
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-table-toolbar")
                self.assertContains(response, f'id="{filter_id}"')

    def test_module_date_ranges_are_inclusive_and_use_the_documented_field(self):
        self.client.force_login(self.staff)
        cases = (
            ("farmers:list", self.new_farmer.record_id, self.old_farmer.record_id),
            ("farm_parcels:list", self.new_parcel.display_name, self.old_parcel.display_name),
            ("crops:list", "Corn", "Rice"),
            ("service_requests:list", self.new_request.request_id, self.old_request.request_id),
            ("interventions:list", self.new_intervention.reference_id, self.old_intervention.reference_id),
        )
        for url_name, included, excluded in cases:
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    reverse(url_name), {"date_from": "2026-02-02", "date_to": "2026-02-02"}
                )
                if url_name == "crops:list":
                    listed = [
                        crop.crop_type
                        for farmer in response.context["object_list"]
                        for crop in farmer.listed_crop_records
                    ]
                    self.assertEqual(listed, ["Corn"])
                else:
                    self.assertContains(response, included)
                    self.assertNotContains(response, excluded)

        self.client.force_login(self.admin)
        activity = self.client.get(
            reverse("activity_logs:list"),
            {"date_from": "2026-02-02", "date_to": "2026-02-02"},
        )
        self.assertContains(activity, "Newer activity")
        self.assertNotContains(activity, "Older activity")

    def test_reversed_date_range_is_rejected_without_partial_filtering(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("farmers:list"),
            {"date_from": "2026-03-01", "date_to": "2026-02-01"},
        )
        self.assertContains(response, "From date must be on or before To date.")
        self.assertContains(response, self.old_farmer.record_id)
        self.assertContains(response, self.new_farmer.record_id)

    def test_account_toolbar_filters_remain_admin_only(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("accounts:list"), {"role": "STAFF", "status": "active"}
        )
        self.assertContains(response, "data-table-toolbar")
        self.assertEqual(list(response.context["object_list"]), [self.staff])

        self.client.force_login(self.staff)
        denied = self.client.get(reverse("accounts:list"))
        self.assertEqual(denied.status_code, 302)
