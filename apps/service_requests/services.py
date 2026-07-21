from django.db import transaction


@transaction.atomic
def update_status(request_obj, status):
    request_obj.status = status
    request_obj.save(update_fields=["status", "updated_at"])
    return request_obj
