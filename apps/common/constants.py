ROLE_ADMIN = "ADMIN"
ROLE_STAFF = "STAFF"
ROLE_CHOICES = ((ROLE_ADMIN, "Administrator"), (ROLE_STAFF, "Staff"))

# Philippine Standard Geographic Code (PSGC), Municipality of Rosario,
# Batangas. Verified against the PSA list of 48 barangays.
ROSARIO_BARANGAYS = (
    "Alupay", "Antipolo", "Bagong Pook", "Balibago", "Bayawang", "Baybayin",
    "Bulihan", "Cahigam", "Calantas", "Colongan", "Itlugan", "Lumbangan",
    "Maalas-As", "Mabato", "Mabunga", "Macalamcam A", "Macalamcam B", "Malaya",
    "Maligaya", "Marilag", "Masaya", "Matamis", "Mavalor", "Mayuro", "Namuco",
    "Namunga", "Natu", "Nasi", "Palakpak", "Pinagsibaan", "Barangay A",
    "Barangay B", "Barangay C", "Barangay D", "Barangay E", "Putingkahoy",
    "Quilib", "Salao", "San Carlos", "San Ignacio", "San Isidro", "San Jose",
    "San Roque", "Santa Cruz", "Timbugan", "Tiquiwan", "Leviste", "Tulos",
)
ROSARIO_BARANGAY_CHOICES = (("", "Select barangay"),) + tuple((name, name) for name in ROSARIO_BARANGAYS)
