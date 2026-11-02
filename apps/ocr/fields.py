# What the form reader is asked to copy for each field. Keep descriptions literal:
# the reader must report what is written, never what it thinks was meant.
FIELD_DESCRIPTIONS = {
    "farmer_name": "Full name of the farmer exactly as written (last name, first name order is allowed).",
    "barangay": "Barangay of the farm, exactly as written.",
    "parcel_name": "Name or description of the farm parcel, if written.",
    "latitude": "Latitude of the farm exactly as written, including any degree signs, minutes, seconds or missing decimal point.",
    "longitude": "Longitude of the farm exactly as written, including any degree signs, minutes, seconds or missing decimal point.",
    "area_hectares": "Farm area in hectares as written (number only). If written in square metres or another unit, copy it with its unit.",
    "commodity": "Main crop or livestock commodity written on the form.",
    "ownership_type": "Tenure written on the form: one of OWNED, TENANT, LEASED, ARB, OTHER, or the words written.",
}
