from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CustomUser


@receiver(post_save, sender=CustomUser)
def ensure_staff_status(sender, instance, created, **kwargs):
    if created and instance.is_superuser and instance.role != "ADMIN":
        instance.role = "ADMIN"
        instance.save(update_fields=["role"])
