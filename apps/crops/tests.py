from datetime import date
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.farm_parcels.models import FarmParcel
from apps.farmers.forms import FarmerSlipBLivelihoodForm
from apps.farmers.models import Farmer

from .forms import CropRecordForm
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
        for crop_type, planted_on in (
            ("Rice", date(2026, 6, 1)),
            ("Coffee", date(2026, 7, 1)),
        ):
            CropRecord.objects.create(
                parcel=cls.parcel,
                crop_type=crop_type,
                area_hectares=Decimal("1.00"),
                planting_date=planted_on,
            )

    def test_farmer_appears_once_and_list_shows_only_most_recent_crop(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("crops:list"))
        self.assertEqual(response.status_code, 200)
        farmers = list(response.context["object_list"])
        self.assertEqual(farmers, [self.farmer])
        self.assertEqual(
            {crop.crop_type for crop in farmers[0].listed_crop_records},
            {"Rice", "Coffee"},
        )
        self.assertEqual(farmers[0].listed_crop_name, "Coffee")
        self.assertContains(response, ">Coffee<")
        self.assertNotContains(response, "Coffee, Rice")
        self.assertContains(response, reverse("crops:farmer_detail", args=[self.farmer.pk]))

    def test_farmer_crop_page_owns_the_detailed_crop_table(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("crops:farmer_detail", args=[self.farmer.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active Commodity Records")
        self.assertContains(response, "Add Commodity Record")
        self.assertContains(response, "Rice")
        self.assertContains(response, "Coffee")
        self.assertContains(response, self.parcel.display_name)

        parcel_response = self.client.get(
            reverse("farm_parcels:detail", args=[self.parcel.pk])
        )
        self.assertNotContains(parcel_response, "Active Commodity Records")
        self.assertNotContains(parcel_response, "Add Commodity Record")

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

    def test_poultry_group_is_available_and_does_not_require_area(self):
        self.farmer.activities = "FARMER_POULTRY"
        self.farmer.save(update_fields=["activities"])
        form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Poultry",
                "cropping_start_month": "January",
                "cropping_end_month": "December",
                "area_hectares": "",
                "number_of_heads": "120",
                "is_organic": "False",
                "is_intercrop": "False",
            }
        )
        choices = {
            value: label
            for _group, group_choices in form.fields["crop_type"].choices
            if isinstance(group_choices, (list, tuple))
            for value, label in group_choices
        }
        self.assertEqual(choices["Poultry"], "🐔 Poultry")
        self.assertNotIn("Rhode Island Red", choices)
        self.assertNotIn("Plymouth Rock", choices)
        self.assertNotIn("Leghorn", choices)
        self.assertNotIn("Gamefowl", choices)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["area_hectares"])
        self.assertEqual(form.cleaned_data["cropping_schedule"], "")
        self.assertFalse(form.cleaned_data["is_intercrop"])
        record = form.save()
        self.assertEqual(record.cropping_schedule, "")

    def test_fishery_commodity_does_not_require_a_cropping_schedule(self):
        self.farmer.livelihood = "FISHERFOLK"
        self.farmer.activities = "FISH_AQUACULTURE"
        self.farmer.save(update_fields=["livelihood", "activities"])
        form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Tilapia",
                "cropping_start_month": "",
                "cropping_end_month": "",
                "area_hectares": "",
                "number_of_heads": "",
                "is_organic": "False",
                "is_intercrop": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cropping_schedule"], "")
        self.assertFalse(form.cleaned_data["is_intercrop"])

    def test_farmer_crop_livelihood_rejects_livestock_commodity(self):
        form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Swine",
                "cropping_start_month": "",
                "cropping_end_month": "",
                "area_hectares": "",
                "number_of_heads": "10",
                "is_organic": "False",
                "is_intercrop": "False",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("crop_type", form.errors)
        self.assertIn(
            "matches this farmer's recorded livelihood",
            form.errors["crop_type"][0],
        )

    def test_livestock_raiser_accepts_livestock_and_rejects_crop_commodity(self):
        self.farmer.livelihood = "LIVESTOCK"
        self.farmer.activities = ""
        self.farmer.save(update_fields=["livelihood", "activities"])
        livestock = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Swine",
                "number_of_heads": "10",
                "is_organic": "False",
                "is_intercrop": "False",
            }
        )
        crop = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Rice",
                "area_hectares": "0.50",
                "is_organic": "False",
                "is_intercrop": "False",
            }
        )

        self.assertTrue(livestock.is_valid(), livestock.errors)
        self.assertFalse(crop.is_valid())
        self.assertIn("crop_type", crop.errors)

    def test_catalog_uses_specific_leafy_vegetables(self):
        form = CropRecordForm()
        values = {
            value
            for _group, group_choices in form.fields["crop_type"].choices
            if isinstance(group_choices, (list, tuple))
            for value, _label in group_choices
        }
        self.assertNotIn("Leafy Vegetables", values)
        self.assertNotIn("Unspecified Leafy Vegetable", values)
        self.assertTrue({"Kangkong", "Pechay", "Mustasa"}.issubset(values))

    def test_livelihood_update_rejects_mismatched_primary_activity(self):
        shared = {
            "transaction_code": "TX-2026-001",
            "change_reason": "CORRECTION",
            "registrant_declaration": "on",
        }
        mismatches = (
            ("FARMER", "FARMER_LIVESTOCK"),
            ("LIVESTOCK", "FISH_CAPTURE"),
            ("POULTRY", "FARMER_CROPS"),
        )
        for livelihood, activity in mismatches:
            with self.subTest(livelihood=livelihood, activity=activity):
                form = FarmerSlipBLivelihoodForm(
                    data={
                        **shared,
                        "livelihood": livelihood,
                        "activities": activity,
                    },
                    instance=self.farmer,
                )
                self.assertFalse(form.is_valid())
                self.assertIn("activities", form.errors)

    def test_livelihood_update_accepts_each_new_exact_activity(self):
        shared = {
            "transaction_code": "TX-2026-002",
            "change_reason": "CORRECTION",
            "registrant_declaration": "on",
        }
        matches = (
            ("FARMER", "FARMER_CROPS"),
            ("LIVESTOCK", "FARMER_LIVESTOCK"),
            ("POULTRY", "FARMER_POULTRY"),
        )
        for livelihood, activity in matches:
            with self.subTest(livelihood=livelihood, activity=activity):
                form = FarmerSlipBLivelihoodForm(
                    data={
                        **shared,
                        "livelihood": livelihood,
                        "activities": activity,
                    },
                    instance=self.farmer,
                )
                self.assertTrue(form.is_valid(), form.errors)

    def test_crop_requires_an_intercropping_yes_or_no_answer(self):
        form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Rice",
                "cropping_start_month": "",
                "cropping_end_month": "",
                "area_hectares": "0.50",
                "number_of_heads": "",
                "is_organic": "False",
                "is_intercrop": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("is_intercrop", form.errors)

    def test_crop_schedule_is_optional_but_a_partial_range_is_rejected(self):
        empty_parcel = FarmParcel.objects.create(
            farmer=self.farmer,
            barangay="Bulihan",
            area_hectares=Decimal("1.00"),
            ownership_type="OWNED",
            land_type="UPLAND",
        )
        base_data = {
            "parcel": empty_parcel.pk,
            "crop_type": "Rice",
            "area_hectares": "0.50",
            "number_of_heads": "",
            "is_organic": "False",
            "is_intercrop": "False",
        }
        optional = CropRecordForm(
            data={
                **base_data,
                "cropping_start_month": "",
                "cropping_end_month": "",
            }
        )
        self.assertTrue(optional.is_valid(), optional.errors)
        self.assertEqual(optional.cleaned_data["cropping_schedule"], "")

        partial = CropRecordForm(
            data={
                **base_data,
                "cropping_start_month": "January",
                "cropping_end_month": "",
            }
        )
        self.assertFalse(partial.is_valid())
        self.assertIn("cropping_end_month", partial.errors)

    def test_common_then_other_then_additional_groups_are_ordered_for_staff(self):
        form = CropRecordForm()
        groups = [
            label
            for label, choices in form.fields["crop_type"].choices
            if isinstance(choices, (list, tuple))
        ]
        self.assertEqual(groups[:2], ["Crops", "Livestock and poultry"])
        self.assertIn("Fisheries and aquaculture", groups)

    def test_add_commodity_loads_parcels_through_search(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("crops:create"))
        self.assertEqual(response.status_code, 200)
        parcel_field = response.context["form"].fields["parcel"]
        self.assertEqual(parcel_field.queryset.count(), 0)
        self.assertEqual(
            parcel_field.widget.attrs["data-search-url"],
            reverse("farm_parcels:map_search"),
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
            {"action": "restore", "status": "inactive"},
        )
        self.assertRedirects(response, f'{reverse("crops:list")}?status=inactive')
        self.assertFalse(CropRecord.objects.filter(is_active=False).exists())
