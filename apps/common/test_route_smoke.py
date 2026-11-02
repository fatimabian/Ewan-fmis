"""A permanent smoke test: every named page is requested as anonymous, staff and admin.

It catches what feature tests miss: a template that does not exist, a page that crashes for one
role, or a protected page that opens for the wrong person. Each address is read only (GET).
"""
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.farmers.views import build_farmer_qr_token
from apps.form_scan.models import FormScan
from apps.interventions.models import Intervention
from apps.inventory.models import InventoryItem
from apps.notifications.models import Notification
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest

# Pages that anyone may open without signing in.
PUBLIC = {
    "authentication:landing", "authentication:login", "authentication:password_reset",
    "authentication:password_reset_done", "authentication:password_reset_complete",
    "authentication:privacy", "authentication:terms", "authentication:register_staff", "health_check",
    "record_session_activity", "expire_idle_session",
}
# Accounts, activity and similar pages belong to administrators; the rest of the system to staff.
ADMIN_ONLY_PREFIXES = ("accounts:", "activity_logs:", "dashboard:admin_home")
SKIP = {"logout"}


def named_routes(patterns, prefix="", namespace=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = f"{namespace}:{pattern.namespace}" if namespace and pattern.namespace else (pattern.namespace or namespace)
            yield from named_routes(pattern.url_patterns, prefix + str(pattern.pattern), inner)
        elif isinstance(pattern, URLPattern) and pattern.name:
            yield (f"{namespace}:{pattern.name}" if namespace else pattern.name), prefix + str(pattern.pattern)


class RouteSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username="smoke-staff", password="Strong-password-731!", role="STAFF")
        cls.admin = User.objects.create_user(username="smoke-admin", password="Strong-password-731!", role="ADMIN")
        farmer = Farmer.objects.create(first_name="Ana", last_name="Cruz", barangay="Bulihan")
        parcel = FarmParcel.objects.create(farmer=farmer, barangay="Bulihan", area_hectares=Decimal("2"), ownership_type="OWNED", coordinates="13.7967000, 121.2351000")
        service = ServiceCatalog.objects.create(name="Seed Assistance", code="SMK", category="Farm Inputs", description="d", processing_time="1 day")
        cls.farmer = farmer
        cls.objects = {
            "farmers": farmer, "farm_parcels": parcel, "service_requests": ServiceRequest.objects.create(farmer=farmer, service=service),
            "crops": CropRecord.objects.create(parcel=parcel, crop_type="Rice", area_hectares=Decimal("1")),
            "interventions": Intervention.objects.create(farmer=farmer, intervention_type="SEEDS", intervention_date="2026-10-01", description="Seeds"),
            "inventory": InventoryItem.objects.create(item_code="SMK-1", name="Seed", category="SEEDS", unit="bag", storage_location="Store"),
            "accounts": cls.admin,
            "notifications": Notification.objects.create(recipient=cls.staff, title="t", message="m"),
        }
        cls.objects["form_scan"] = FormScan.objects.create(created_by=cls.staff, image_sha256="0" * 64, target="PARCEL")

    def url_for(self, name, route):
        namespace = name.split(":")[0]
        kwargs = {}
        for param in re.findall(r"<(?:\w+:)?(\w+)>", route):
            if param == "token":
                kwargs[param] = build_farmer_qr_token(self.farmer.pk)
            elif param in {"pk", "id"} and namespace in self.objects:
                kwargs[param] = self.objects[namespace].pk
            elif param == "page":
                kwargs[param] = 1
            else:
                return None  # needs data this test does not create (photos, reset links, history rows)
        try:
            return reverse(name, kwargs=kwargs)
        except NoReverseMatch:
            return None

    def test_no_page_crashes_and_every_role_is_kept_in_its_lane(self):
        routes = sorted(set(named_routes(get_resolver().url_patterns)))
        checked = 0
        problems = []
        for name, route in routes:
            if name in SKIP:
                continue
            url = self.url_for(name, route)
            if url is None:
                continue
            checked += 1
            for role, user in (("anonymous", None), ("staff", self.staff), ("admin", self.admin)):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                try:
                    response = self.client.get(url)
                except Exception as error:  # a crash that the test client re-raises
                    problems.append(f"{role} {url}: {type(error).__name__}: {error}")
                    continue
                if response.status_code >= 500:
                    problems.append(f"{role} {url}: HTTP {response.status_code}")
                if role == "anonymous" and name not in PUBLIC and response.status_code == 200:
                    problems.append(f"anonymous can open {url} ({name})")
                if role == "staff" and name.startswith(ADMIN_ONLY_PREFIXES) and response.status_code == 200:
                    problems.append(f"staff can open the administrator page {url}")
                if role == "admin" and name.split(":")[0] in {"farmers", "farm_parcels", "crops", "form_scan", "gis"} and response.status_code == 200:
                    problems.append(f"admin can open the staff page {url}")
        self.assertEqual(problems, [])
        self.assertGreater(checked, 80)  # the walk really covered the system


class AccountDeleteAddressTests(TestCase):
    def test_a_typed_delete_link_goes_to_the_account_instead_of_crashing(self):
        User = get_user_model()
        admin = User.objects.create_user(username="del-admin", password="Strong-password-731!", role="ADMIN")
        other = User.objects.create_user(username="del-staff", password="Strong-password-731!", role="STAFF")
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:delete", args=[other.pk]))
        self.assertRedirects(response, reverse("accounts:detail", args=[other.pk]))
        self.assertTrue(User.objects.filter(pk=other.pk, is_active=True).exists())  # a GET never changes anything
