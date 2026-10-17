from django.conf import settings
from django.core.mail import send_mail
from django.core.management import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one production SMTP delivery test to an office-controlled mailbox."

    def add_arguments(self, parser):
        parser.add_argument("recipient")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        if not recipient or "@" not in recipient:
            raise CommandError("Provide a valid recipient email address.")
        delivered = send_mail(
            "FMIS email delivery test",
            "This confirms that FMIS can deliver account activation and password recovery email.",
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        if delivered != 1:
            raise CommandError("The SMTP service did not confirm delivery.")
        self.stdout.write(self.style.SUCCESS(f"FMIS test email accepted for {recipient}."))
