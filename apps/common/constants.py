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
    ("CROP-MONITOR", "Crop Monitoring Support", "Technical Services"),
    ("OTHER", "Other Agricultural Concern", "Other"),
)

ROSARIO_MUNICIPALITY = "Rosario"
ROSARIO_PROVINCE = "Batangas"
ROSARIO_REGION = "CALABARZON Region IV-A"

# Clear commodity names used for Rosario encoding and dashboard summaries.
# Avoid broad labels such as "High Value Crops" because staff need to know the
# actual crop or animal commodity recorded for each farmer.
_ROSARIO_COMMON_COMMODITIES = (
    ("Rice", "Rice (Palay)"),
    ("Corn", "Corn"),
    ("Coconut", "Coconut"),
    ("Banana", "Banana"),
    ("Mango", "Mango"),
    ("Calamansi / Mandarin", "Calamansi / Mandarin Orange"),
    ("Squash", "Squash"),
    ("Ginger", "Ginger"),
    ("Turmeric", "Turmeric"),
    ("Swine", "Swine / Hogs"),
    ("Poultry", "Poultry"),
    ("Dairy Carabao", "Dairy Carabao"),
)
_ROSARIO_ADDITIONAL_CROPS = (
    ("Coffee", "Coffee"),
    ("Cacao", "Cacao"),
    ("Cassava", "Cassava"),
    ("Sweet Potato", "Sweet Potato"),
    ("Peanut", "Peanut"),
    ("Mung Bean", "Mung Bean"),
    ("Eggplant", "Eggplant"),
    ("Tomato", "Tomato"),
    ("String Beans", "String Beans"),
    ("Bitter Gourd", "Bitter Gourd"),
    ("Chili Pepper", "Chili Pepper"),
    ("Leafy Vegetables", "Leafy Vegetables"),
)
_ROSARIO_ADDITIONAL_ANIMALS = (
    ("Carabao", "Carabao"),
    ("Cattle", "Cattle"),
    ("Goat", "Goat"),
    ("Sheep", "Sheep"),
    ("Rabbit", "Rabbit"),
    ("Broiler Chicken", "Broiler Chicken"),
    ("Layer Chicken", "Layer Chicken"),
    ("Native Chicken", "Native Chicken"),
    ("Duck", "Duck"),
    ("Quail", "Quail"),
    ("Turkey", "Turkey"),
)
_ROSARIO_ADDITIONAL_FISHERIES = (
    ("Tilapia", "Tilapia"),
    ("Freshwater Fish", "Other Freshwater Fish"),
    ("Aquaculture", "Other Aquaculture Commodity"),
)


def _symbol_choices(items):
    return tuple((value, f"{crop_symbol(value)} {label}") for value, label in items)


_ROSARIO_COMMON_ANIMALS = tuple(
    item for item in _ROSARIO_COMMON_COMMODITIES
    if item[0] in {"Swine", "Poultry", "Dairy Carabao"}
)
_ROSARIO_COMMON_CROPS = tuple(
    item for item in _ROSARIO_COMMON_COMMODITIES
    if item[0] not in {"Swine", "Poultry", "Dairy Carabao"}
)

ROSARIO_CROP_CHOICES = (
    ("", "Select crop or commodity"),
    ("Crops", _symbol_choices(_ROSARIO_COMMON_CROPS + _ROSARIO_ADDITIONAL_CROPS)),
    (
        "Livestock and poultry",
        _symbol_choices(_ROSARIO_COMMON_ANIMALS + _ROSARIO_ADDITIONAL_ANIMALS),
    ),
    ("Fisheries and aquaculture", _symbol_choices(_ROSARIO_ADDITIONAL_FISHERIES)),
    (
        "Other",
        (("Other Crop / Commodity", f"{crop_symbol('Other Crop / Commodity')} Other Commodity"),),
    ),
)

CROP_COMMODITIES = frozenset(
    value for value, _label in _ROSARIO_COMMON_COMMODITIES + _ROSARIO_ADDITIONAL_CROPS
    if value not in {"Swine", "Poultry", "Dairy Carabao"}
)

FISHERY_COMMODITIES = frozenset(value for value, _label in _ROSARIO_ADDITIONAL_FISHERIES)

ROSARIO_COMMODITY_VALUES = frozenset(
    value
    for value, _label in (
        _ROSARIO_COMMON_COMMODITIES
        + _ROSARIO_ADDITIONAL_CROPS
        + _ROSARIO_ADDITIONAL_ANIMALS
        + _ROSARIO_ADDITIONAL_FISHERIES
        + (("Other Crop / Commodity", "Other Commodity"),)
    )
)

LIVESTOCK_COMMODITIES = frozenset(
    {
        "Livestock", "Poultry", "Dairy Carabao",
        "Carabao", "Cattle", "Swine", "Goat", "Sheep", "Broiler Chicken",
        "Layer Chicken", "Native Chicken", "Rhode Island Red", "Plymouth Rock",
        "Leghorn", "Gamefowl", "Duck", "Quail", "Turkey", "Rabbit",
    }
)

COMMODITY_DETAIL_TO_GROUP = {
    "Rice": "Rice",
    "Corn": "Corn",
    "Coconut": "Coconut",
    "High Value Crops": "Mixed Fruits & Vegetables",
    "Banana": "Banana",
    "Mango": "Mango",
    "Calamansi": "Calamansi",
    "Calamansi / Mandarin": "Calamansi / Mandarin",
    "Coffee": "Coffee",
    "Cacao": "Cacao",
    "Cassava": "Cassava",
    "Sweet Potato": "Sweet Potato",
    "Peanut": "Peanut",
    "Mung Bean": "Mung Bean",
    "Eggplant": "Eggplant",
    "Tomato": "Tomato",
    "String Beans": "String Beans",
    "Squash": "Squash",
    "Ginger": "Ginger",
    "Turmeric": "Turmeric",
    "Bitter Gourd": "Bitter Gourd",
    "Chili Pepper": "Chili Pepper",
    "Leafy Vegetables": "Leafy Vegetables",
    "Livestock": "Mixed Livestock",
    "Dairy Carabao": "Dairy Carabao",
    "Carabao": "Carabao",
    "Cattle": "Cattle",
    "Swine": "Swine",
    "Goat": "Goat",
    "Sheep": "Sheep",
    "Rabbit": "Rabbit",
    "Poultry": "Poultry",
    "Broiler Chicken": "Poultry",
    "Layer Chicken": "Poultry",
    "Native Chicken": "Poultry",
    "Rhode Island Red": "Poultry",
    "Plymouth Rock": "Poultry",
    "Leghorn": "Poultry",
    "Gamefowl": "Poultry",
    "Duck": "Poultry",
    "Quail": "Poultry",
    "Turkey": "Poultry",
    "Other Crop / Commodity": "Other Commodity",
    "Tilapia": "Tilapia",
    "Freshwater Fish": "Freshwater Fish",
    "Aquaculture": "Aquaculture",
}
_COMMODITY_GROUP_LOOKUP = {
    name.casefold(): group for name, group in COMMODITY_DETAIL_TO_GROUP.items()
}


def commodity_group(value):
    """Return the municipal summary group without altering the saved detail."""
    normalized = (value or "").strip().casefold()
    return _COMMODITY_GROUP_LOOKUP.get(normalized, "Other Commodity")

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

# PSA Philippine Standard Geographic Code identifiers for Rosario, Batangas.
# Names and codes are kept together so boundary imports never rely on a fuzzy
# barangay-name match. Source: PSA PSGC municipality code 0401021000.
ROSARIO_PSGC_CODE = "0401021000"
ROSARIO_BARANGAY_PSGC = {
    name: f"0401021{index:03d}"
    for index, name in enumerate(ROSARIO_BARANGAYS, start=1)
}
