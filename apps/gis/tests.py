from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
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
        Farmer.objects.filter(pk=cls.maria.pk).update(livelihood="FARMER", sex="FEMALE", is_pwd=True)
        Farmer.objects.filter(pk=cls.juan.pk).update(livelihood="LIVESTOCK", sex="MALE")
        cls.pending = ServiceRequest.objects.create(farmer=cls.maria, service=service, status="PENDING", priority="HIGH")
        cls.intervention = Intervention.objects.create(
            farmer=cls.maria, intervention_type="SEEDS", intervention_date="2026-10-01", description="Rice seeds", status="COMPLETED")
        # Saving an intervention already creates its recipient, so adjust rather than add.
        cls.received, _ = InterventionRecipient.objects.update_or_create(
            intervention=cls.intervention, farmer=cls.maria, defaults={"status": "RECEIVED"})
        cls.waiting, _ = InterventionRecipient.objects.update_or_create(
            intervention=cls.intervention, farmer=cls.juan, defaults={"status": "PENDING"})
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
        self.assertContains(response, "Map by")
        for chip in ("Farmers", "Parcels", "Commodities", "Requests", "Interventions"):
            self.assertContains(response, chip)
        self.assertContains(response, 'id="gisChips"')
        self.assertContains(response, 'id="gisFilterToggle"')
        self.assertContains(response, 'id="gisParcelDirectory"')
        self.assertContains(response, 'id="gisParcelPinStatus"')
        self.assertContains(response, 'id="gisDetailPhoto"')
        self.assertContains(response, "Apply Filters")
        self.assertContains(response, reverse("gis:map"))  # sidebar entry
        self.assertNotContains(response, reverse("form_scan:upload"))  # scanning lives inside the forms
        config = response.context["config"]
        self.assertEqual(config["parcelListUrl"], reverse("farm_parcels:map_parcels"))
        self.assertIn("{id}", config["parcelDetailUrl"])

    def test_parcel_list_uses_gis_instead_of_a_separate_map_button(self):
        response = self.client.get(reverse("farm_parcels:list"))
        self.assertNotContains(response, "Map View")


class LevelTests(GISTestCase):
    def test_level_one_is_a_density_grid_with_insights(self):
        data = self.data(layer="parcels")
        self.assertEqual(data["level"], 1)
        self.assertNotIn("points", data)  # no per-record ids or statuses at this level
        self.assertNotIn("heat", data)
        self.assertEqual(data["size"], 0.01)
        self.assertEqual(sum(cell["count"] for cell in data["cells"]), 3)
        self.assertTrue(all(cell["tier"] in (1, 2, 3) for cell in data["cells"]))
        self.assertEqual([(t["barangay"], t["count"]) for t in data["insights"]["busiest"]], [("Alupay", 3), ("Bulihan", 1)])
        self.assertEqual(data["insights"]["attention"], [{"barangay": "Alupay", "count": 1}])
        facet = data["insights"]["facet"]
        self.assertEqual((facet["title"], facet["filter"]), ("By ownership", "ownership"))
        self.assertEqual({(i["value"], i["count"]) for i in facet["items"]}, {("OWNED", 3), ("TENANT", 1)})
        self.assertEqual((data["total"], data["mapped"], data["unmapped"]), (4, 3, 1))

    def test_grid_tiers_have_legend_ranges(self):
        data = self.data(layer="farmers")
        self.assertTrue(data["tiers"])
        self.assertTrue(all(set(t) == {"tier", "label"} for t in data["tiers"]))

    def test_insights_follow_the_filters(self):
        coconut = self.data(layer="parcels", commodity="Coconut")
        self.assertEqual([t["barangay"] for t in coconut["insights"]["busiest"]], ["Alupay"])
        self.assertLessEqual(len(self.data(layer="parcels")["insights"]["busiest"]), 5)

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
        self.assertIn(["Farmer", f"{self.maria.record_id} Maria Santos"], card["rows"])
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
        self.assertEqual((rice["total"], rice["cells"][0]["barangay"]), (1, "Bulihan"))

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


class FilterTests(GISTestCase):
    def test_search_finds_farmer_and_record_references_across_layers(self):
        expectations = {
            "farmers": ("Maria", 1),
            "parcels": (f"P-{self.p1.pk:04d}", 1),
            "commodities": ("Rice", 1),
            "requests": ("Seed Assistance", 1),
            "interventions": (f"INT-{self.intervention.pk:04d}", 2),
        }
        for layer, (search, expected) in expectations.items():
            status = "" if layer != "requests" else "open"
            self.assertEqual(self.data(layer=layer, search=search, status=status)["total"], expected, layer)

    def test_farmer_number_range_applies_to_every_layer(self):
        low, high = self.maria.pk, self.maria.pk
        for layer, expected in (("farmers", 1), ("parcels", 1), ("commodities", 1), ("requests", 1), ("interventions", 1)):
            data = self.data(layer=layer, farmer_from=low, farmer_to=high, status="" if layer != "requests" else "open")
            self.assertEqual(data["total"], expected, layer)
        self.assertEqual(self.data(layer="farmers", farmer_from=self.juan.pk, farmer_to=self.nopin.pk)["total"], 2)
        self.assertEqual(self.data(layer="farmers", farmer_from=self.nopin.pk + 1)["total"], 0)

    def test_farmer_filters(self):
        self.assertEqual(self.data(layer="farmers", livelihood="LIVESTOCK")["total"], 1)
        self.assertEqual(self.data(layer="farmers", sex="FEMALE")["total"], 1)
        self.assertEqual(self.data(layer="farmers", group="pwd")["total"], 1)
        self.assertEqual(self.data(layer="farmers", group="four_ps")["total"], 0)

    def test_parcel_filters(self):
        self.assertEqual(self.data(layer="parcels", ownership="TENANT")["total"], 1)
        self.assertEqual(self.data(layer="parcels", area_min="1.5", area_max="2")["total"], 2)
        self.assertEqual(self.data(layer="parcels", area_min="5")["total"], 0)

    def test_commodity_filters(self):
        CropRecord.objects.filter(pk=self.rice.pk).update(is_organic=True)
        self.assertEqual(self.data(layer="commodities", organic="yes")["total"], 1)
        self.assertEqual(self.data(layer="commodities", organic="no")["total"], 1)
        self.assertEqual(self.data(layer="commodities", area_min="1.8")["total"], 1)

    def test_request_filters(self):
        self.assertEqual(self.data(layer="requests", priority="HIGH")["total"], 1)
        self.assertEqual(self.data(layer="requests", priority="LOW")["total"], 0)
        self.assertEqual(self.data(layer="requests", service="Farm Inputs")["total"], 1)
        self.assertEqual(self.data(layer="requests", date_from="2999-01-01")["total"], 0)

    def test_interventions_layer(self):
        data = self.data(layer="interventions")
        self.assertEqual((data["total"], data["attention"]), (2, 1))
        self.assertEqual(self.data(layer="interventions", status="RECEIVED")["total"], 1)
        self.assertEqual(self.data(layer="interventions", kind="TRAINING")["total"], 0)
        self.assertEqual(self.data(layer="interventions", date_to="2026-01-01")["total"], 0)
        points = self.data(layer="interventions", barangay="Bulihan")["points"]
        self.assertEqual((points[0]["id"], points[0]["status"]), (self.received.pk, "good"))
        card = self.client.get(reverse("gis:detail"), {"layer": "interventions", "id": self.received.pk}).json()
        self.assertEqual(card["title"], "Seeds / planting materials")
        self.assertIn(["Status", "Received"], card["rows"])

    def test_filters_not_offered_by_a_layer_are_ignored(self):
        self.assertEqual(self.data(layer="parcels", livelihood="LIVESTOCK")["total"], 4)

    def test_page_offers_all_five_layers_and_filter_specs(self):
        page = self.client.get(reverse("gis:map"))
        self.assertContains(page, "Interventions")
        config = page.context["config"]
        self.assertEqual([layer["key"] for layer in config["layers"]], ["farmers", "parcels", "commodities", "requests", "interventions"])
        self.assertIn("Farm Inputs", [value for value, _ in config["filterSpecs"]["service"]["options"]])


class ValidationTests(GISTestCase):
    def test_bad_parameters_are_rejected(self):
        for params in ({"layer": "nope"}, {"layer": "parcels", "barangay": "Atlantis"},
                       {"layer": "parcels", "commodity": "Unobtainium"}, {"layer": "parcels", "status": "weird"},
                       {"layer": "farmers", "farmer_from": "abc"}, {"layer": "farmers", "farmer_from": "0"},
                       {"layer": "farmers", "farmer_from": "9", "farmer_to": "3"}, {"layer": "farmers", "livelihood": "pirate"},
                       {"layer": "parcels", "area_min": "-1"}, {"layer": "parcels", "area_min": "5", "area_max": "1"},
                       {"layer": "requests", "date_from": "yesterday"}, {"layer": "requests", "date_from": "2026-12-01", "date_to": "2026-01-01"}):
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

    def test_parcel_gallery_lists_only_active_private_photo_urls(self):
        from apps.farm_parcels.models import FarmParcelPhoto
        first = FarmParcelPhoto.objects.create(parcel=self.p1, image="private/first.jpg")
        second = FarmParcelPhoto.objects.create(parcel=self.p1, image="private/second.jpg")
        hidden = FarmParcelPhoto.objects.create(parcel=self.p1, image="private/hidden.jpg", is_active=False)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farm_parcels:map_detail", args=[self.p1.pk]))
        self.assertEqual(response.status_code, 200)
        expected = [reverse("farm_parcels:photo_view", args=[self.p1.pk, photo.pk]) for photo in (second, first)]
        self.assertEqual(response.json()["photo_urls"], expected)
        self.assertNotIn("private/", response.content.decode())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("farm_parcels:map_detail", args=[self.p1.pk])).status_code, 302)
