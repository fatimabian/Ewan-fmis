from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from .models import Farmer
from .rsbsa_pdf import build_rsbsa_pdf


class RSBSAFormPrintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(username="print-staff", password="Print-test-593!", role="STAFF")
        cls.farmer = Farmer.objects.create(first_name="Maria Corazon", middle_name="Reyes", last_name="Dela Cruz", barangay="Alupay", birth_date=date(1985, 4, 12), phone_number="09171234567", spouse_name="Juan Miguel Dela Cruz", highest_education="Senior High School", philsys_registered=True, philsys_pcn="1234-5678-9012-3456")

    def setUp(self):
        self.client.force_login(self.staff)

    def test_default_pdf_uses_official_letter_form_and_places_names_in_their_cells(self):
        reader = PdfReader(BytesIO(build_rsbsa_pdf(self.farmer)))
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual(reader.trailer["/Root"]["/ViewerPreferences"]["/PrintScaling"], "/None")
        self.assertEqual(tuple(reader.pages[0].mediabox), (0, 0, 612, 792))
        self.assertGreater(len(reader.pages[0].images), 0)
        placements = []
        reader.pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size: placements.append((text.strip(), tm[4], tm[5])))
        surname = next(item for item in placements if item[0] == "DELA CRUZ")
        self.assertTrue(72 <= surname[1] <= 295)
        self.assertEqual(surname[2], 628)
        self.assertIn("JUAN MIGUEL DELA CRUZ", reader.pages[0].extract_text())
        self.assertNotIn(self.farmer.registration_reference, reader.pages[0].extract_text())
        self.assertEqual(reader.metadata.title, f"RSBSA Enrollment Form - {self.farmer.record_id}")

    def test_boxed_birthdate_and_all_three_crop_blocks_stay_in_their_input_rows(self):
        for index in range(3):
            parcel = FarmParcel.objects.create(farmer=self.farmer, barangay="Alupay", area_hectares="1", ownership_type="OWNED")
            CropRecord.objects.create(parcel=parcel, crop_type=f"ROWMARKER{index}")
        reader = PdfReader(BytesIO(build_rsbsa_pdf(self.farmer)))
        first, second = [], []
        reader.pages[0].extract_text(visitor_text=lambda text, cm, tm, font, size: first.append((text.strip(), tm[4], tm[5])))
        reader.pages[1].extract_text(visitor_text=lambda text, cm, tm, font, size: second.append((text.strip(), tm[4], tm[5])))
        birthday = [item for item in first if item[2] == 407 and item[1] < 190 and len(item[0]) == 1]
        self.assertEqual("".join(item[0] for item in birthday), "APR121985")
        self.assertLess(abs(birthday[-1][1] - 183.9), 3)
        for index, baseline in enumerate((702.3, 564.6, 426.3)):
            value = next(item for item in second if item[0] == f"ROWMARKER{index}")
            self.assertEqual(value[2], baseline)
            self.assertTrue(309 <= value[1] <= 385)

    def test_text_only_pdf_has_no_background_and_does_not_fill_signatures(self):
        reader = PdfReader(BytesIO(build_rsbsa_pdf(self.farmer, mode="text", offset_x=1, offset_y=-1)))
        self.assertEqual(len(reader.pages[0].images), 0)
        positions = []
        reader.pages[1].extract_text(visitor_text=lambda text, cm, tm, font, size: positions.append((text.strip(), tm[4], tm[5])))
        self.assertFalse(any(text and x > 345 and 140 < y < 175 for text, x, y in positions))
        self.assertIn("MARIA CORAZON REYES DELA CRUZ", reader.pages[1].extract_text())

    def test_continuation_sheets_include_every_active_parcel_and_crop(self):
        for index in range(4):
            parcel = FarmParcel.objects.create(farmer=self.farmer, barangay=f"LOCATION{index}", area_hectares="1.00", ownership_type="OWNED")
            for crop_index in range(6 if index == 0 else 1):
                CropRecord.objects.create(parcel=parcel, crop_type=f"CROP{index}X{crop_index}", number_of_heads=0)
            if index == 0:
                for intercrop in range(2):
                    CropRecord.objects.create(parcel=parcel, crop_type=f"INTERCROP{intercrop}", is_intercrop=True)
        archived = FarmParcel.objects.create(farmer=self.farmer, barangay="ARCHIVEDLOCATION", area_hectares="1.00", ownership_type="OWNED", is_active=False)
        CropRecord.objects.create(parcel=archived, crop_type="ARCHIVEDCROP")
        reader = PdfReader(BytesIO(build_rsbsa_pdf(self.farmer)))
        self.assertEqual(len(reader.pages), 3)
        text = "\n".join(page.extract_text() for page in reader.pages)
        for index in range(4):
            self.assertIn(f"LOCATION{index}", text)
            for crop_index in range(6 if index == 0 else 1):
                self.assertIn(f"CROP{index}X{crop_index}", text)
        self.assertIn("INTERCROP1", text)
        self.assertNotIn("ARCHIVEDLOCATION", text)
        self.assertNotIn("ARCHIVEDCROP", text)

    def test_print_page_exposes_preview_and_validated_pdf_options(self):
        response = self.client.get(reverse("farmers:rsbsa_print", args=[self.farmer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open PDF to print")
        self.assertContains(response, "Actual size / 100%")
        url = reverse("farmers:rsbsa_form_pdf", args=[self.farmer.pk])
        pdf = self.client.get(url, {"mode": "text", "offset_x": "1.5", "scale": "99.5", "download": "1"})
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertEqual(pdf["X-Frame-Options"], "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", pdf["Content-Security-Policy"])
        self.assertIn("attachment", pdf["Content-Disposition"])
        self.assertEqual(self.client.get(url, {"offset_x": "500"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"scale": "nan"}).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
