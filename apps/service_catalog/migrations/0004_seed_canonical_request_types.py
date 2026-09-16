from django.db import migrations


SERVICES = (
    ("RSBSA-REG", "RSBSA Registration or Record Update", "Farmer Records"),
    ("PARCEL-UPD", "Farm Parcel or Crop Record Update", "Farmer Records"),
    ("CERT-DATA", "Certification, Endorsement, or Data Request", "Farmer Records"),
    ("SEED", "Seed Assistance", "Farm Inputs"),
    ("PLANT-MAT", "Planting Materials Assistance", "Farm Inputs"),
    ("FERTILIZER", "Fertilizer or Soil Amendment Assistance", "Farm Inputs"),
    ("SOIL-TEST", "Soil Testing or Fertility Advice", "Technical Services"),
    ("PEST-DISEASE", "Crop Pest or Disease Assistance", "Technical Services"),
    ("CROP-TECH", "Crop Production Technical Assistance", "Technical Services"),
    ("IRRIGATION", "Irrigation or Water Management Assistance", "Technical Services"),
    ("MACHINERY", "Farm Machinery or Equipment Assistance", "Equipment"),
    ("TRAINING", "Training, Seminar, or Farm Advisory", "Capacity Building"),
    ("ORGANIC", "Organic Agriculture Support", "Programs"),
    ("HVC-URBAN", "High-Value Crops or Urban Gardening Support", "Programs"),
    ("LIVESTOCK-VET", "Livestock or Veterinary Assistance", "Livestock"),
    ("ANIMAL-DISP", "Animal Dispersal Assistance", "Livestock"),
    ("FISHERIES", "Fisheries or Aquaculture Assistance", "Fisheries"),
    ("INSURANCE", "Crop Insurance Referral or Assistance", "Referral Services"),
    ("CREDIT", "Agricultural Credit or Financing Referral", "Referral Services"),
    ("MARKET", "Market Linkage or Product Promotion Assistance", "Market Support"),
    ("FCA", "Farmer Cooperative or Association Support", "Organization Support"),
    ("DISASTER", "Farm Damage Assessment or Disaster Assistance", "Emergency Support"),
    ("OTHER", "Other Agricultural Concern", "Other"),
)


def seed_request_types(apps, schema_editor):
    ServiceCatalog = apps.get_model("service_catalog", "ServiceCatalog")
    for code, name, category in SERVICES:
        ServiceCatalog.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "description": f"Standard {name.lower()} request handled by the Office for Agricultural Services.",
                "processing_time": "Subject to assessment and program availability",
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("service_catalog", "0003_servicecatalog_icon_name")]

    operations = [migrations.RunPython(seed_request_types, migrations.RunPython.noop)]
