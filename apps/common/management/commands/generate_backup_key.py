import base64
import secrets

from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Generate a new AES-256 FMIS backup recovery key for protected configuration."

    def handle(self, *args, **options):
        key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        self.stdout.write("Store this value in the protected server environment and an offline recovery record:")
        self.stdout.write(f"FMIS_BACKUP_ENCRYPTION_KEY={key}")
        self.stdout.write(self.style.WARNING("Do not email, commit, or paste this recovery key into FMIS."))
