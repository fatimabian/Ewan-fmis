from .crop_symbols import crop_symbol


ROLE_ADMIN = "ADMIN"
ROLE_STAFF = "STAFF"
ROLE_CHOICES = ((ROLE_ADMIN, "Administrator"), (ROLE_STAFF, "Staff"))
ASSIGNABLE_ROLE_CHOICES = ((ROLE_STAFF, "Staff"),)

ROSARIO_MUNICIPALITY = "Rosario"
ROSARIO_PROVINCE = "Batangas"
ROSARIO_REGION = "CALABARZON Region IV-A"

# The municipal office explicitly supports rice, corn, vegetables, coconut,
# and other high-value crops. Keep the list practical for local encoding while
# retaining an Other option for commodities not yet listed.
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
    ("Other Crop / Commodity", "Other Crop / Commodity"),
)
ROSARIO_CROP_CHOICES = (("", "Select crop or commodity"),) + tuple(
    (value, f"{crop_symbol(value)} {label}") for value, label in _ROSARIO_CROP_LABELS
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
