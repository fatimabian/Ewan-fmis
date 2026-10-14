from .crop_symbols import crop_symbol


ROLE_ADMIN = "ADMIN"
ROLE_STAFF = "STAFF"
ROLE_CHOICES = ((ROLE_ADMIN, "Administrator"), (ROLE_STAFF, "Staff"))
ASSIGNABLE_ROLE_CHOICES = ((ROLE_STAFF, "Staff"),)

MONTH_CHOICES = (
    ("", "Select month"),
    ("January", "January"),
    ("February", "February"),
    ("March", "March"),
    ("April", "April"),
    ("May", "May"),
    ("June", "June"),
    ("July", "July"),
    ("August", "August"),
    ("September", "September"),
    ("October", "October"),
    ("November", "November"),
    ("December", "December"),
)

# Canonical request types used by the Office for Agricultural Services. The
# database table remains a protected reference table so historical requests
# retain their foreign-key relationships without requiring a catalog UI.
CANONICAL_AGRICULTURAL_SERVICES = (
    ("RSBSA-REG", "RSBSA Registration or Record Update", "Farmer Records"),
    ("PARCEL-UPD", "Farm Parcel or Commodity Record Update", "Farmer Records"),
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

ROSARIO_MUNICIPALITY = "Rosario"
ROSARIO_PROVINCE = "Batangas"
ROSARIO_REGION = "CALABARZON Region IV-A"

# Rosario crop, livestock, and poultry commodities. Livestock terminology follows
# the commodity names used by the Philippine Statistics Authority.
_ROSARIO_CROP_LABELS = (
    ("Rice", "Rice (Palay)"),
    ("Corn", "Corn"),
    ("Coconut", "Coconut"),
    ("Banana", "Banana"),
    ("Mango", "Mango"),
    ("Calamansi", "Calamansi"),
    ("Coffee", "Coffee"),
    ("Cacao", "Cacao"),
    ("Cassava", "Cassava"),
    ("Sweet Potato", "Sweet Potato (Kamote)"),
    ("Peanut", "Peanut"),
    ("Mung Bean", "Mung Bean (Monggo)"),
    ("Eggplant", "Eggplant"),
    ("Tomato", "Tomato"),
    ("String Beans", "String Beans (Sitaw)"),
    ("Squash", "Squash (Kalabasa)"),
    ("Bitter Gourd", "Bitter Gourd (Ampalaya)"),
    ("Chili Pepper", "Chili Pepper"),
    ("Leafy Vegetables", "Leafy Vegetables"),
    ("Carabao", "Carabao"),
    ("Cattle", "Cattle"),
    ("Swine", "Swine"),
    ("Goat", "Goat"),
    ("Sheep", "Sheep"),
    ("Broiler Chicken", "Broiler Chicken"),
    ("Layer Chicken", "Layer Chicken"),
    ("Native Chicken", "Native Chicken (Manok na Tagalog)"),
    ("Rhode Island Red", "Rhode Island Red"),
    ("Plymouth Rock", "Plymouth Rock"),
    ("Leghorn", "Leghorn"),
    ("Gamefowl", "Gamefowl (Panabong)"),
    ("Duck", "Duck"),
    ("Quail", "Quail"),
    ("Turkey", "Turkey"),
    ("Rabbit", "Rabbit"),
    ("Other Crop / Commodity", "Other Commodity"),
)
ROSARIO_CROP_CHOICES = (("", "Select crop or commodity"),) + tuple(
    (value, f"{crop_symbol(value)} {label}") for value, label in _ROSARIO_CROP_LABELS
)

LIVESTOCK_COMMODITIES = frozenset(
    {
        "Carabao", "Cattle", "Swine", "Goat", "Sheep", "Broiler Chicken",
        "Layer Chicken", "Native Chicken", "Rhode Island Red", "Plymouth Rock",
        "Leghorn", "Gamefowl", "Duck", "Quail", "Turkey", "Rabbit",
    }
)

# Philippine Standard Geographic Code (PSGC), Municipality of Rosario,
# Batangas. Verified against the PSA list of 48 barangays.
ROSARIO_BARANGAYS = (
    "Alupay",
    "Antipolo",
    "Bagong Pook",
    "Balibago",
    "Bayawang",
    "Baybayin",
    "Bulihan",
    "Cahigam",
    "Calantas",
    "Colongan",
    "Itlugan",
    "Lumbangan",
    "Maalas-As",
    "Mabato",
    "Mabunga",
    "Macalamcam A",
    "Macalamcam B",
    "Malaya",
    "Maligaya",
    "Marilag",
    "Masaya",
    "Matamis",
    "Mavalor",
    "Mayuro",
    "Namuco",
    "Namunga",
    "Natu",
    "Nasi",
    "Palakpak",
    "Pinagsibaan",
    "Barangay A",
    "Barangay B",
    "Barangay C",
    "Barangay D",
    "Barangay E",
    "Putingkahoy",
    "Quilib",
    "Salao",
    "San Carlos",
    "San Ignacio",
    "San Isidro",
    "San Jose",
    "San Roque",
    "Santa Cruz",
    "Timbugan",
    "Tiquiwan",
    "Leviste",
    "Tulos",
)
ROSARIO_BARANGAY_CHOICES = (("", "Select barangay"),) + tuple(
    (name, name) for name in ROSARIO_BARANGAYS
)
