from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.interventions.models import Intervention
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest
from apps.farmers.models import Farmer

from .models import InventoryItem, InventoryMovement
from .services import record_inventory_movement


class InventoryModuleTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="inventory.staff",
            password="test-password",
            role="STAFF",
            first_name="Inventory",
            last_name="Staff",
        )
        self.admin = get_user_model().objects.create_user(
            username="inventory.admin",
            password="test-password",
            role="ADMIN",
        )
        self.item = InventoryItem.objects.create(
            item_code="SEED-001",
            name="Certified Rice Seed",
            category="SEEDS",
            unit="bag",
            reorder_level=Decimal("10.00"),
            storage_location="Municipal Stockroom A",
        )
        self.intervention = Intervention.objects.create(
            scope="ALL",
            status="COMPLETED",
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Municipal rice seed distribution",
            recorded_by=self.staff,
        )

    def test_staff_can_open_inventory_with_standard_toolbar_and_filters(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("inventory:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Search Inventory")
        self.assertContains(response, "Filter Inventory")
        self.assertContains(response, "Stock Movements")
        self.assertContains(response, self.item.item_code)
        self.assertContains(response, "Rows per page:")

    def test_inventory_supports_bounded_rows_per_page_pagination(self):
        InventoryItem.objects.bulk_create(
            [
                InventoryItem(
                    item_code=f"ITEM-{index:03d}",
                    name=f"Inventory Item {index:03d}",
                    category="OTHER",
                    unit="unit",
                    reorder_level=0,
                    storage_location="Main Stockroom",
                )
                for index in range(30)
            ]
        )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("inventory:list"), {"per_page": "10", "page": "2"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.per_page, 10)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 4)
        self.assertContains(response, "of 4")

    def test_item_code_is_generated_and_not_user_editable(self):
        self.client.force_login(self.staff)
        create_page = self.client.get(reverse("inventory:item_create"))
        self.assertNotContains(create_page, 'name="item_code"')
        response = self.client.post(
            reverse("inventory:item_create"),
            {
                "name": "Hybrid Corn Seed",
                "category": "SEEDS",
                "unit": "bag",
                "reorder_level": "5.00",
                "storage_location": "Municipal Stockroom B",
                "expiration_date": "",
                "notes": "",
            },
        )
        created = InventoryItem.objects.get(name="Hybrid Corn Seed")
        self.assertEqual(created.item_code, f"INV-{created.pk:05d}")
        self.assertRedirects(response, reverse("inventory:list"))

        edit_page = self.client.get(reverse("inventory:item_edit", args=[created.pk]))
        self.assertNotContains(edit_page, 'name="item_code"')
        self.assertContains(edit_page, created.item_code)

    def test_administrator_cannot_open_staff_inventory(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("inventory:list"))
        self.assertRedirects(
            response, reverse("dashboard:home"), fetch_redirect_response=False
        )

    def test_receipt_and_intervention_release_update_balance(self):
        receipt = record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("25.00"),
            reference="DR-1001",
            recorded_by=self.staff,
        )
        release = record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RELEASE,
            quantity=Decimal("7.00"),
            intervention=self.intervention,
            recorded_by=self.staff,
        )
        self.item.refresh_from_db()
        self.assertEqual(receipt.balance_after, Decimal("25.00"))
        self.assertEqual(release.balance_after, Decimal("18.00"))
        self.assertEqual(self.item.stock_on_hand, Decimal("18.00"))
        self.assertEqual(release.intervention, self.intervention)

    def test_release_requires_intervention_and_cannot_overdraw_stock(self):
        record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("5.00"),
            recorded_by=self.staff,
        )
        with self.assertRaisesMessage(ValidationError, "Choose the intervention"):
            record_inventory_movement(
                item=self.item,
                movement_type=InventoryMovement.RELEASE,
                quantity=Decimal("1.00"),
                recorded_by=self.staff,
            )
        with self.assertRaisesMessage(ValidationError, "Only 5.00 bag is available"):
            record_inventory_movement(
                item=self.item,
                movement_type=InventoryMovement.RELEASE,
                quantity=Decimal("6.00"),
                intervention=self.intervention,
                recorded_by=self.staff,
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock_on_hand, Decimal("5.00"))
        self.assertEqual(self.item.movements.count(), 1)

    def test_release_form_links_movement_and_intervention_detail(self):
        record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("20.00"),
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("inventory:movement_create"),
            {
                "item": self.item.pk,
                "movement_type": InventoryMovement.RELEASE,
                "quantity": "4.00",
                "intervention": self.intervention.pk,
                "reference": "RIS-2026-01",
                "remarks": "Released to beneficiaries",
            },
        )
        movement = InventoryMovement.objects.get(movement_type=InventoryMovement.RELEASE)
        self.assertRedirects(response, reverse("inventory:detail", args=[self.item.pk]))
        self.assertEqual(movement.intervention, self.intervention)
        intervention_response = self.client.get(
            reverse("interventions:detail", args=[self.intervention.pk])
        )
        self.assertContains(intervention_response, "Inventory Released")
        self.assertContains(intervention_response, movement.movement_id)
        self.assertContains(intervention_response, self.item.name)

    def test_request_release_creates_and_links_delivered_intervention(self):
        farmer = Farmer.objects.create(
            first_name="Maria", last_name="Santos", barangay="Alupay"
        )
        service, _ = ServiceCatalog.objects.get_or_create(
            code="SEED",
            defaults={
                "name": "Seed Assistance",
                "category": "Farm Inputs",
                "description": "Seed support",
                "processing_time": "Depends on assessment",
            },
        )
        request = ServiceRequest.objects.create(
            scope="INDIVIDUAL",
            farmer=farmer,
            service=service,
            subject=service.name,
            status="PENDING",
            assigned_to=self.staff,
        )
        record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("20.00"),
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("inventory:movement_create"),
            {
                "service_request": request.pk,
                "intervention": "",
                "item": self.item.pk,
                "movement_type": InventoryMovement.RELEASE,
                "quantity": "5.00",
                "reference": "RIS-2026-02",
                "remarks": "Released at the municipal office",
            },
        )
        self.assertRedirects(response, reverse("inventory:detail", args=[self.item.pk]))
        intervention = Intervention.objects.get(service_request=request)
        movement = InventoryMovement.objects.get(
            movement_type=InventoryMovement.RELEASE,
            reference="RIS-2026-02",
        )
        request.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(intervention.status, "COMPLETED")
        self.assertEqual(intervention.farmer, farmer)
        self.assertEqual(
            list(intervention.recipients.values_list("farmer_id", flat=True)),
            [farmer.pk],
        )
        self.assertEqual(movement.intervention, intervention)
        self.assertEqual(request.status, "COMPLETED")
        self.assertEqual(self.item.stock_on_hand, Decimal("15.00"))

    def test_item_and_movement_filters_only_return_matches(self):
        other = InventoryItem.objects.create(
            item_code="TOOL-001",
            name="Knapsack Sprayer",
            category="TOOLS",
            unit="unit",
            reorder_level=Decimal("2.00"),
            storage_location="Equipment Room",
        )
        record_inventory_movement(
            item=other,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("3.00"),
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)
        item_response = self.client.get(
            reverse("inventory:list"), {"category": "TOOLS"}
        )
        self.assertContains(item_response, other.name)
        self.assertNotContains(item_response, self.item.name)
        movement_response = self.client.get(
            reverse("inventory:list"),
            {"tab": "movements", "movement_type": InventoryMovement.RECEIPT},
        )
        self.assertContains(movement_response, "Stock received")
        self.assertContains(movement_response, other.name)

    def test_item_with_remaining_stock_cannot_be_archived(self):
        record_inventory_movement(
            item=self.item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("1.00"),
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.post(reverse("inventory:item_archive", args=[self.item.pk]))
        self.assertRedirects(response, reverse("inventory:detail", args=[self.item.pk]))
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_active)

