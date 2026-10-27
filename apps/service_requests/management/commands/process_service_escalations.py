import json

from django.core.management.base import BaseCommand

from apps.service_requests.services import process_due_escalations


class Command(BaseCommand):
    help = "Record and notify newly overdue service requests. Safe to run repeatedly."

    def handle(self, *args, **options):
        result = process_due_escalations()
        self.stdout.write(json.dumps(result, sort_keys=True))
