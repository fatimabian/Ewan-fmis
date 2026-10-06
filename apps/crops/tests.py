from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer

from .models import CropRecord


class GroupedCropListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            username="cropstaff",
            password="Strong-password-731!",
            role="STAFF",
        )
        cls.farmer = Farmer.objects.create(
            first_name="Maria",
            last_name="Reyes",
            barangay="Bulihan",
        )
        cls.parcel = FarmParcel.objects.create(
            farmer=cls.farmer,
            barangay="Bulihan",
            area_hectares=Decimal("2.00"),
            ownership_type="OWNED",
            land_type="UPLAND",
        )
        for crop_type in ("Rice", "Coffee"):
            CropRecord.objects.create(
                parcel=cls.parcel,
                crop_type=crop_type,
                area_hectares=Decimal("1.00"),
                planting_date=date(2026, 6, 1),
            )

    def test_farmer_appears_once_with_all_matching_crops(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("crops:list"))
        self.assertEqual(response.status_code, 200)
        farmers = list(response.context["object_list"])
        self.assertEqual(farmers, [self.farmer])
        self.assertEqual(
            {crop.crop_type for crop in farmers[0].listed_crop_records},
            {"Rice", "Coffee"},
        )
        self.assertContains(response, reverse("crops:farmer_detail", args=[self.farmer.pk]))

    def test_farmer_crop_page_owns_the_detailed_crop_table(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("crops:farmer_detail", args=[self.farmer.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current Crop Records")
        self.assertContains(response, "Add Crop Record")
        self.assertContains(response, "Rice")
        self.assertContains(response, "Coffee")
        self.assertContains(response, self.parcel.display_name)

        parcel_response = self.client.get(
            reverse("farm_parcels:detail", args=[self.parcel.pk])
        )
        self.assertNotContains(parcel_response, "Current Crop Records")
        self.assertNotContains(parcel_response, "Add Crop Record")

        create_response = self.client.get(
            reverse("crops:create"), {"farmer": self.farmer.pk}
        )
        self.assertEqual(
            list(create_response.context["form"].fields["parcel"].queryset),
            [self.parcel],
        )

    def test_crop_filter_keeps_one_farmer_and_only_matching_crop(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("crops:list"), {"crop_type": "Rice"})
        farmers = list(response.context["object_list"])
        self.assertEqual(len(farmers), 1)
        self.assertEqual(
            [crop.crop_type for crop in farmers[0].listed_crop_records],
            ["Rice"],
        )

    def test_grouped_trash_action_archives_only_displayed_crop_records(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("crops:farmer_archive", args=[self.farmer.pk]),
            {"crop_type": "Rice"},
        )
        self.assertRedirects(response, f'{reverse("crops:list")}?crop_type=Rice')
        self.assertFalse(CropRecord.objects.get(crop_type="Rice").is_active)
        self.assertTrue(CropRecord.objects.get(crop_type="Coffee").is_active)
        self.assertEqual(
            CropRecord.objects.get(crop_type="Rice").archived_by,
            self.staff,
        )

    def test_grouped_archived_action_restores_records(self):
        CropRecord.objects.update(is_active=False, archived_by=self.staff)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("crops:farmer_archive", args=[self.farmer.pk]),
            {"action": "restore", "status": "archived"},
        )
        self.assertRedirects(response, f'{reverse("crops:list")}?status=archived')
        self.assertFalse(CropRecord.objects.filter(is_active=False).exists())
