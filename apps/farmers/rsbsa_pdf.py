from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


TEMPLATE_PATH = (
    Path(settings.BASE_DIR)
    / "apps"
    / "farmers"
    / "assets"
    / "rsbsa"
    / "RSBSA-REGISTRATION-FORM-01-2024.pdf"
)
PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def _clean(value):
    return str(value or "").strip().upper()


def _safe_extension(value):
    extension = _clean(value).replace(",", "")
    allowed = {"JR", "JR.", "SR", "SR.", "II", "III", "IV", "V", "VI"}
    return extension if extension in allowed else ""


def _farmer_print_name(farmer):
    return " ".join(
        part
        for part in (
            _clean(farmer.first_name),
            _clean(farmer.middle_name),
            _clean(farmer.last_name),
            _safe_extension(farmer.extension_name),
        )
        if part
    )


def _write(pdf, value, x, y, width, size=7, align="left"):
    value = _clean(value)
    if not value:
        return
    font = "Helvetica"
    selected = size
    while selected > 4.5 and stringWidth(value, font, selected) > width:
        selected -= 0.25
    if stringWidth(value, font, selected) > width:
        while value and stringWidth(value + "...", font, selected) > width:
            value = value[:-1]
        value += "..."
    pdf.setFont(font, selected)
    if align == "center":
        pdf.drawCentredString(x + width / 2, y, value)
    else:
        pdf.drawString(x, y, value)


def _check(pdf, x, y, checked, size=8.5):
    """Place an X at the measured center of an official form checkbox."""
    if checked:
        pdf.setFont("Helvetica-Bold", size)
        pdf.drawCentredString(x, y - (size * 0.32), "X")


def _write_boxed_characters(pdf, value, centers, y, size=7):
    """Center one character in each of the form's pre-printed boxes."""
    characters = [character for character in _clean(value) if character.isalnum()]
    pdf.setFont("Helvetica", size)
    for character, x in zip(characters, centers):
        pdf.drawCentredString(x, y, character)


def _local_mobile_digits(value):
    """Return a local mobile number without inventing missing source digits."""
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if digits.startswith("63"):
        digits = "0" + digits[2:]
    elif digits.startswith("9"):
        digits = "0" + digits
    return digits


def _split_name(value):
    parts = _clean(value).split()
    if not parts:
        return "", "", "", ""
    if len(parts) == 1:
        return parts[0], "", "", ""
    if len(parts) == 2:
        return parts[0], "", parts[1], ""
    return parts[0], " ".join(parts[1:-1]), parts[-1], ""


def _write_name_parts(pdf, value, columns, y, size=6):
    """Write a full name into the official first/middle/surname/extension cells."""
    for part, (x, width) in zip(_split_name(value), columns):
        _write(pdf, part, x, y, width, size, "center")


def _membership_names(value):
    normalized = _clean(value).replace("\n", ",").replace(";", ",")
    return [name.strip() for name in normalized.split(",") if name.strip()][:3]


def _education_key(value):
    value = _clean(value)
    checks = {
        "PRE": "preschool",
        "ELEMENTARY": "elementary",
        "HIGH SCHOOL": "high_school",
        "JUNIOR": "junior",
        "SENIOR": "senior",
        "COLLEGE": "college",
        "POST": "postgraduate",
        "VOCATIONAL": "vocational",
        "NONE": "none",
    }
    return next((key for text, key in checks.items() if text in value), "")


def _page_one(pdf, farmer):
    transaction_code = farmer.registration_reference
    if farmer.philsys_registered is True:
        _write(pdf, farmer.philsys_pcn, 124, 688, 309, 7)
    elif farmer.philsys_registered is False:
        _write(pdf, farmer.philsys_trn or transaction_code, 124, 666, 309, 7)
    else:
        _write(pdf, transaction_code, 124, 666, 309, 7)

    if farmer.photo_available:
        try:
            pdf.drawImage(
                farmer.photo.path,
                445,
                650,
                117,
                130,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        except (OSError, ValueError):
            pass

    _write(pdf, farmer.last_name, 72, 628, 223, 8, "center")
    _write(pdf, farmer.first_name, 309, 628, 245, 8, "center")
    _write(pdf, farmer.middle_name, 72, 604, 223, 8, "center")
    extension_name = _safe_extension(farmer.extension_name)
    _write(pdf, extension_name, 309, 604, 80, 8, "center")
    _check(pdf, 98.6, 586.6, not _clean(farmer.middle_name))
    _check(pdf, 309.4, 584.6, not extension_name)
    _check(pdf, 461.6, 586.5, farmer.sex == "MALE")
    _check(pdf, 506.1, 586.2, farmer.sex == "FEMALE")

    # Boxed fields use a deliberately lower baseline so text sits in the
    # middle of each blank instead of touching the top rule when printed.
    _write(pdf, farmer.house_lot_purok, 165, 557, 104, 7, "center")
    _write(pdf, farmer.street_sitio, 279, 557, 130, 7, "center")
    _write(pdf, farmer.barangay, 420, 557, 140, 7, "center")
    _write(pdf, farmer.city_municipality, 66, 524, 160, 7, "center")
    _write(pdf, farmer.province, 233, 524, 180, 7, "center")
    _write(pdf, farmer.region, 420, 524, 140, 7, "center")

    if farmer.birth_date:
        birth_value = farmer.birth_date.strftime("%b%d%Y")
        _write_boxed_characters(
            pdf,
            birth_value,
            (68.5, 81.0, 93.5, 118.0, 130.5, 152.0, 164.5, 177.0, 189.5),
            407,
            7,
        )
    _write(pdf, farmer.place_of_birth, 201, 407, 130, 7, "center")
    mobile_digits = _local_mobile_digits(farmer.phone_number)
    # The official form already prints "09" in its first two mobile boxes.
    if mobile_digits.startswith("09"):
        mobile_digits = mobile_digits[2:]
    _write_boxed_characters(
        pdf,
        mobile_digits,
        (384.5, 400.5, 416.5, 432.5, 448.5, 464.5, 480.5, 496.5, 512.5),
        407,
        7,
    )
    name_columns = ((66, 65), (132, 68), (201, 82), (284, 46))
    _write_name_parts(pdf, farmer.mother_maiden_name, name_columns, 363)

    civil_checks = {
        "SINGLE": (70.7, 328.4),
        "WIDOWED": (174.4, 329.1),
        "MARRIED": (70.7, 314.6),
        "SEPARATED": (174.4, 315.0),
    }
    if farmer.civil_status in civil_checks:
        _check(pdf, *civil_checks[farmer.civil_status], True)
    _write_name_parts(pdf, farmer.spouse_name, name_columns, 281)

    education_checks = {
        "preschool": (344.0, 323.5),
        "senior": (444.1, 323.3),
        "elementary": (344.0, 310.2),
        "college": (444.0, 309.9),
        "high_school": (344.0, 297.1),
        "postgraduate": (444.1, 296.6),
        "junior": (344.0, 284.1),
        "vocational": (444.1, 284.0),
        "none": (506.1, 283.7),
    }
    education = _education_key(farmer.highest_education)
    if education in education_checks:
        _check(pdf, *education_checks[education], True)

    _write(pdf, farmer.rsbsa_number, 124, 254, 208, 7, "center")
    _write(pdf, farmer.valid_id_type, 430, 241, 118, 6)
    _write(pdf, farmer.valid_id_number, 430, 222, 118, 7)

    religion = _clean(farmer.religion)
    _check(pdf, 71.7, 228.3, "CHRIST" in religion)
    _check(pdf, 144.7, 228.5, "ISLAM" in religion)
    _check(pdf, 200.3, 228.6, bool(religion) and "CHRIST" not in religion and "ISLAM" not in religion and "NONE" not in religion)
    _check(pdf, 264.3, 228.4, religion == "NONE")
    _check(pdf, 72.6, 201.9, farmer.is_indigenous)
    _check(pdf, 108.7, 201.8, not farmer.is_indigenous)
    _write(pdf, farmer.indigenous_group, 200, 198, 125, 6)
    _check(pdf, 341.8, 202.5, farmer.is_pwd)
    _check(pdf, 379.8, 202.5, not farmer.is_pwd)
    _check(pdf, 454.6, 199.1, farmer.is_four_ps, 6.5)
    _check(pdf, 483.7, 199.1, not farmer.is_four_ps, 6.5)
    membership_boxes = ((66, 157), (226, 157), (386, 174))
    for membership, (x, width) in zip(_membership_names(farmer.fca_membership), membership_boxes):
        _write(pdf, membership, x, 165, width, 6, "center")

    livelihood_checks = {
        "FARMER": (74.3, 129.6),
        "FARMWORKER": (183.7, 129.6),
        "FISHERFOLK": (375.8, 129.8),
        "AGRI_YOUTH": (486.3, 129.8),
    }
    if farmer.livelihood in livelihood_checks:
        _check(pdf, *livelihood_checks[farmer.livelihood], True)
    stub_columns = ((165, 52), (218, 52), (271, 57), (329, 27))
    for value, (x, width) in zip(
        (farmer.first_name, farmer.middle_name, farmer.last_name, extension_name),
        stub_columns,
    ):
        _write(pdf, value, x, 44, width, 5.3, "center")
    _write(pdf, transaction_code, 111, 20, 245, 7, "center")


def _parcel_crops(parcel):
    crops = list(parcel.crops.filter(is_active=True).order_by("pk"))
    regular = [crop for crop in crops if not crop.is_intercrop][:4]
    intercrop = next((crop for crop in crops if crop.is_intercrop), None)
    return regular, intercrop


def _page_two(pdf, farmer, parcels):
    blocks = [
        {
            "top": 711,
            "crop_rows": [690, 670, 650, 630],
            "intercrop": 600,
            "tiller": 574,
            "ancestral": ((161.3, 668.8), (179.2, 668.5)),
            "arb": ((161.3, 660.9), (179.2, 660.9)),
            "ownership": {"OWNED": (80.1, 629.2), "LEASED": (145.6, 629.2), "TENANT": (80.1, 622.0), "OTHER": (145.6, 622.0), "ARB": (145.6, 622.0)},
        },
        {
            "top": 568,
            "crop_rows": [547, 527, 507, 487],
            "intercrop": 457,
            "tiller": 431,
            "ancestral": ((160.9, 532.1), (178.7, 531.9)),
            "arb": ((160.9, 524.2), (178.7, 524.2)),
            "ownership": {"OWNED": (79.7, 492.5), "LEASED": (145.2, 492.5), "TENANT": (79.7, 485.3), "OTHER": (145.2, 485.3), "ARB": (145.2, 485.3)},
        },
        {
            "top": 425,
            "crop_rows": [404, 384, 364, 344],
            "intercrop": 314,
            "tiller": 288,
            "ancestral": ((160.3, 395.0), (178.1, 394.7)),
            "arb": ((160.3, 387.1), (178.1, 387.1)),
            "ownership": {"OWNED": (79.1, 355.4), "LEASED": (144.7, 355.4), "TENANT": (79.1, 348.2), "OTHER": (144.7, 348.2), "ARB": (144.7, 348.2)},
        },
    ]
    for parcel, block in zip(parcels[:3], blocks):
        top = block["top"]
        _write(pdf, parcel.barangay, 78, top - 8, 150, 6, "center")
        _write(pdf, f"{parcel.municipality}, {parcel.province}", 78, top - 20, 150, 5.5, "center")
        _write(pdf, parcel.area_hectares, 163, top - 40, 42, 7, "center")
        _check(pdf, *block["ancestral"][0], parcel.within_ancestral_domain is True, 5.5)
        _check(pdf, *block["ancestral"][1], parcel.within_ancestral_domain is False, 5.5)
        _check(pdf, *block["arb"][0], parcel.agrarian_reform_beneficiary is True, 5.5)
        _check(pdf, *block["arb"][1], parcel.agrarian_reform_beneficiary is False, 5.5)
        proof_codes = {
            "Certificate of Land Transfer": "A",
            "Emancipation Patent": "B",
            "Individual CLOA": "C",
            "Collective CLOA": "D",
            "Co-Ownership CLOA": "E",
            "Agricultural Sales Patent": "F",
            "Homestead Patent": "G",
            "Free Patent": "H",
            "Certificate of Title": "I",
            "Ancestral Domain Title": "J",
            "Ancestral Land Title": "K",
            "Tax Declaration": "L",
            "OTHER": "M",
        }
        proof = proof_codes.get(parcel.ownership_document, "")
        _write(pdf, proof, 198, top - 78, 29, 4.5, "center")
        ownership_center = block["ownership"].get(parcel.ownership_type)
        if ownership_center:
            _check(pdf, *ownership_center, True, 5.5)
        _write_name_parts(
            pdf,
            parcel.land_owner_name,
            ((78, 38), (117, 40), (158, 45), (204, 23)),
            top - 118,
            4.8,
        )
        _write(pdf, parcel.land_owner_rsbsa_number, 94, top - 127, 133, 5.5, "center")

        regular, intercrop = _parcel_crops(parcel)
        for crop, y in zip(regular, block["crop_rows"]):
            _write(pdf, crop.cropping_schedule, 238, y, 74, 5.5, "center")
            _write(pdf, crop.crop_type, 313, y, 80, 5.5, "center")
            _write(pdf, crop.area_hectares, 394, y, 47, 5.5, "center")
            _write(pdf, crop.number_of_heads, 442, y, 43, 5.5, "center")
            farm_type = {"Irrigated": "1", "Rainfed Upland": "2", "Rainfed Lowland": "3"}.get(parcel.farm_type, "N/A")
            _write(pdf, farm_type, 487, y, 42, 5.5, "center")
            _write(pdf, "Y" if crop.is_organic else "N", 531, y, 34, 5.5, "center")
        if intercrop:
            y = block["intercrop"]
            _write(pdf, intercrop.cropping_schedule, 238, y, 74, 5.5, "center")
            _write(pdf, intercrop.crop_type, 313, y, 80, 5.5, "center")
            _write(pdf, intercrop.area_hectares, 394, y, 47, 5.5, "center")
            _write(pdf, intercrop.number_of_heads, 442, y, 43, 5.5, "center")
            farm_type = {"Irrigated": "1", "Rainfed Upland": "2", "Rainfed Lowland": "3"}.get(parcel.farm_type, "N/A")
            _write(pdf, farm_type, 487, y, 42, 5.5, "center")
            _write(pdf, "Y" if intercrop.is_organic else "N", 531, y, 34, 5.5, "center")

        tiller_y = block["tiller"] + 7
        if parcel.rotational_tiller is True:
            _write(pdf, _farmer_print_name(farmer), 245, tiller_y + 10, 140, 5.2, "center")
            _write(pdf, farmer.rsbsa_number, 245, tiller_y - 1, 140, 5.2, "center")
        _write(pdf, parcel.remarks, 399, tiller_y, 159, 5.2)

    _write(pdf, _farmer_print_name(farmer), 123, 157, 235, 7, "center")


def build_rsbsa_pdf(farmer):
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as error:
        raise ImportError("Install pypdf to generate the official RSBSA form.") from error

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError("The official RSBSA print template is unavailable.")

    overlay = BytesIO()
    pdf = canvas.Canvas(overlay, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    _page_one(pdf, farmer)
    pdf.showPage()
    parcels = list(
        farmer.parcels.filter(is_active=True)
        .prefetch_related("crops")
        .order_by("pk")[:3]
    )
    _page_two(pdf, farmer, parcels)
    pdf.showPage()
    pdf.save()
    overlay.seek(0)

    template_reader = PdfReader(str(TEMPLATE_PATH))
    overlay_reader = PdfReader(overlay)
    writer = PdfWriter()
    for index, template_page in enumerate(template_reader.pages):
        template_page.merge_page(overlay_reader.pages[index])
        writer.add_page(template_page)
    writer.add_metadata(
        {
            "/Title": f"RSBSA Enrollment Form - {farmer.full_name}",
            "/Author": "Office for Agricultural Services - Rosario, Batangas",
            "/Subject": f"Single-farmer RSBSA printout for {farmer.record_id}",
        }
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def rsbsa_pdf_response(farmer):
    response = HttpResponse(build_rsbsa_pdf(farmer), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="rsbsa_{farmer.record_id.lower()}_{farmer.last_name.lower()}.pdf"'
    )
    return response
