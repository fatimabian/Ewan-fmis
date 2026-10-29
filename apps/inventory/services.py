from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import InventoryItem, InventoryMovement


@transaction.atomic
def record_inventory_movement(*, item, movement_type, quantity, intervention=None, reference="", remarks="", recorded_by=None):
    """Record an immutable movement and update stock under a row lock."""
    locked_item = InventoryItem.objects.select_for_update().get(pk=item.pk)
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValidationError("Quantity must be greater than zero.")
    if movement_type == InventoryMovement.RELEASE and intervention is None:
        raise ValidationError("Choose the intervention receiving this stock release.")
    if movement_type in InventoryMovement.INBOUND_TYPES:
        new_balance = locked_item.stock_on_hand + quantity
    elif movement_type in InventoryMovement.OUTBOUND_TYPES:
        if quantity > locked_item.stock_on_hand:
            raise ValidationError(
                f"Only {locked_item.stock_on_hand} {locked_item.unit} is available."
            )
        new_balance = locked_item.stock_on_hand - quantity
    else:
        raise ValidationError("Choose a valid stock movement type.")
    InventoryItem.objects.filter(pk=locked_item.pk).update(
        stock_on_hand=new_balance,
        updated_at=timezone.now(),
    )
    movement = InventoryMovement.objects.create(
        item=locked_item,
        movement_type=movement_type,
        quantity=quantity,
        intervention=intervention,
        reference=reference,
        remarks=remarks,
        balance_after=new_balance,
        recorded_by=recorded_by,
    )
    locked_item.stock_on_hand = new_balance
    return movement
