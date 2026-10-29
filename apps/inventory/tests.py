from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.interventions.models import Intervention

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

