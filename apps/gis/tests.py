from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest


class GISTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username="gisstaff", password="Strong-password-731!", role="STAFF")
        cls.admin = User.objects.create_user(username="gisadmin", password="Strong-password-731!", role="ADMIN")
        cls.maria = Farmer.objects.create(first_name="Maria", last_name="Santos", barangay="Bulihan", registration_status="SKIPPED")
        cls.juan = Farmer.objects.create(first_name="Juan", last_name="Reyes", barangay="Alupay")
        cls.nopin = Farmer.objects.create(first_name="Ana", last_name="Lopez", barangay="Alupay")
        cls.inactive = Farmer.objects.create(first_name="Old", last_name="Farmer", barangay="Alupay", is_active=False)
        cls.p1 = FarmParcel.objects.create(farmer=cls.maria, barangay="Bulihan", area_hectares="1.5", ownership_type="OWNED", coordinates="13.7967000, 121.2351000")
        cls.p2 = FarmParcel.objects.create(farmer=cls.juan, barangay="Alupay", area_hectares="2", ownership_type="TENANT", coordinates="13.8404000, 121.2922000")
        cls.p3 = FarmParcel.objects.create(farmer=cls.nopin, barangay="Alupay", area_hectares="1", ownership_type="OWNED")
        cls.p_out = FarmParcel.objects.create(farmer=cls.juan, barangay="Alupay", area_hectares="1", ownership_type="OWNED", coordinates="14.5995000, 120.9842000")
        cls.rice = CropRecord.objects.create(parcel=cls.p1, crop_type="Rice", area_hectares="1.5")
        cls.coconut = CropRecord.objects.create(parcel=cls.p2, crop_type="Coconut", area_hectares="2")
        service = ServiceCatalog.objects.create(name="Seed Assistance", code="SEED-T", category="Farm Inputs", description="d", processing_time="1 day")
        cls.pending = ServiceRequest.objects.create(farmer=cls.maria, service=service, status="PENDING")
        cls.done = ServiceRequest.objects.create(farmer=cls.juan, service=service, status="COMPLETED")

    def setUp(self):
        self.client.force_login(self.staff)

    def data(self, **params):
        response = self.client.get(reverse("gis:data"), params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class AccessTests(GISTestCase):
    def test_anonymous_and_admin_are_redirected(self):
        for who in (None, self.admin):
            self.client.logout()
            if who:
                self.client.force_login(who)
            for name in ("gis:map", "gis:data", "gis:detail"):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302, (who, name))

    def test_page_renders_and_navigation_links_to_it(self):
        response = self.client.get(reverse("gis:map"))
        self.assertContains(response, "GIS Map")
        for layer in ("Farmers", "Farm parcels", "Commodities", "Service requests"):
            self.assertContains(response, layer)
        self.assertContains(response, reverse("gis:map"))  # sidebar entry
        self.assertNotContains(response, reverse("form_scan:upload"))  # scanning lives inside the forms


class LevelTests(GISTestCase):
    def test_level_one_is_a_heat_map_with_a_short_top_list(self):
        data = self.data(layer="parcels")
        self.assertEqual(data["level"], 1)
        self.assertNotIn("points", data)  # no per-record ids or statuses at this level
        self.assertEqual(sorted(data["heat"]), sorted([[13.7967, 121.2351], [13.8404, 121.2922], [14.5995, 120.9842]]))
        self.assertEqual([(t["barangay"], t["count"]) for t in data["top"]], [("Alupay", 2), ("Bulihan", 1)])
        self.assertEqual({b["barangay"]: b["count"] for b in data["bubbles"]}, {"Bulihan": 1, "Alupay": 2})
        self.assertEqual((data["total"], data["mapped"], data["unmapped"]), (4, 3, 1))

    def test_top_list_is_limited_and_follows_filters(self):
        self.assertLessEqual(len(self.data(layer="parcels")["top"]), 5)
        coconut = self.data(layer="parcels", commodity="Coconut")
        self.assertEqual([t["barangay"] for t in coconut["top"]], ["Alupay"])
        self.assertEqual(coconut["heat"], [[13.8404, 121.2922]])

    def test_level_two_returns_points_with_no_personal_data(self):
        data = self.data(layer="parcels", barangay="Alupay")
        self.assertEqual(data["level"], 2)
        self.assertEqual({p["id"] for p in data["points"]}, {self.p2.pk, self.p_out.pk})
        self.assertEqual(set(data["points"][0]), {"id", "lat", "lng", "status"})

    def test_pins_outside_rosario_are_marked_for_attention(self):
        data = self.data(layer="parcels", barangay="Alupay")
        statuses = {p["id"]: p["status"] for p in data["points"]}
        self.assertEqual(statuses[self.p_out.pk], "attention")
        self.assertEqual(data["attention"], 1)

    def test_level_three_detail_card(self):
        card = self.client.get(reverse("gis:detail"), {"layer": "parcels", "id": self.p1.pk}).json()
        self.assertEqual(card["title"], f"P-{self.p1.pk:04d}")
        self.assertIn(["Farmer", "Maria Santos"], card["rows"])
        self.assertLessEqual(len(card["rows"]), 5)
        self.assertEqual(card["url"], reverse("farm_parcels:detail", args=[self.p1.pk]))


class LayerTests(GISTestCase):
    def test_farmers_layer_uses_parcel_pin_when_farmer_has_none(self):
        data = self.data(layer="farmers")
        self.assertEqual(data["total"], 3)  # inactive farmer hidden
        self.assertEqual(data["mapped"], 2)  # Ana has no mapped parcel
        statuses = {p["id"]: p["status"] for p in self.data(layer="farmers", barangay="Bulihan")["points"]}
        self.assertEqual(statuses, {self.maria.pk: "attention"})  # registration SKIPPED

    def test_commodity_layer_and_filter(self):
        self.assertEqual(self.data(layer="commodities")["total"], 2)
        rice = self.data(layer="commodities", commodity="Rice")
        self.assertEqual((rice["total"], rice["bubbles"][0]["barangay"]), (1, "Bulihan"))

    def test_commodity_filter_applies_to_parcels_and_farmers(self):
        self.assertEqual(self.data(layer="parcels", commodity="Coconut")["total"], 1)
        self.assertEqual(self.data(layer="farmers", commodity="Coconut")["total"], 1)

    def test_attention_only_filter(self):
        data = self.data(layer="parcels", status="attention")
        self.assertEqual((data["total"], data["attention"]), (1, 1))

    def test_requests_layer_defaults_to_open_and_filters_by_status(self):
        data = self.data(layer="requests")
        self.assertEqual(data["total"], 1)
        self.assertEqual(self.data(layer="requests", status="COMPLETED")["total"], 1)
        points = self.data(layer="requests", barangay="Bulihan")["points"]
        self.assertEqual((points[0]["id"], points[0]["status"]), (self.pending.pk, "attention"))
        card = self.client.get(reverse("gis:detail"), {"layer": "requests", "id": self.pending.pk}).json()
        self.assertEqual(card["title"], "Seed Assistance")

    def test_commodity_and_farmer_detail_cards(self):
        crop = self.client.get(reverse("gis:detail"), {"layer": "commodities", "id": self.rice.pk}).json()
        self.assertEqual(crop["title"], "Rice")
        farmer = self.client.get(reverse("gis:detail"), {"layer": "farmers", "id": self.maria.pk}).json()
        self.assertIn(["Parcels", "1 (1.5 ha)"], farmer["rows"])

    def test_every_layer_declares_at_most_three_legend_colours(self):
        from .layers import LAYERS

        for layer in LAYERS.values():
            self.assertLessEqual(len(layer.legend), 3, layer.key)
            self.assertLessEqual(len({status for status, _ in layer.legend}), 3)


class ValidationTests(GISTestCase):
    def test_bad_parameters_are_rejected(self):
        for params in ({"layer": "nope"}, {"layer": "parcels", "barangay": "Atlantis"},
                       {"layer": "parcels", "commodity": "Unobtainium"}, {"layer": "parcels", "status": "weird"}):
            self.assertEqual(self.client.get(reverse("gis:data"), params).status_code, 400, params)

    def test_detail_404s_for_unknown_or_hidden_records(self):
        url = reverse("gis:detail")
        self.assertEqual(self.client.get(url, {"layer": "parcels", "id": 99999}).status_code, 404)
        self.assertEqual(self.client.get(url, {"layer": "parcels", "id": "abc"}).status_code, 404)
        self.assertEqual(self.client.get(url, {"layer": "nope", "id": 1}).status_code, 404)
        self.assertEqual(self.client.get(url, {"layer": "farmers", "id": self.inactive.pk}).status_code, 404)

    def test_empty_result_is_not_an_error(self):
        data = self.data(layer="commodities", barangay="Tulos")
        self.assertEqual((data["total"], data["points"]), (0, []))
