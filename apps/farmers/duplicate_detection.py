"""Explainable, bounded duplicate-candidate checks for farmer registration.

This is deliberately a fuzzy-matching baseline, not a machine-learning model.
An ML classifier must not be enabled until OAS supplies verified pair labels.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date

from django.core import signing
from django.db.models import Q

from .models import Farmer


REVIEW_SALT = "fmis.farmers.duplicate-review.v1"
REVIEW_MAX_AGE_SECONDS = 20 * 60
MAX_DATABASE_CANDIDATES = 120
MAX_REVIEW_MATCHES = 5
FLAG_THRESHOLD = 76


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def normalize_suffix(value):
    normalized = normalize_text(value).replace(" ", "")
    return {
        "junior": "jr",
        "jr": "jr",
        "senior": "sr",
        "sr": "sr",
        "ii": "ii",
        "iii": "iii",
        "iv": "iv",
    }.get(normalized, normalized)


def _similarity(left, right):
    """Return an edit-distance similarity percentage without external services."""
    left = normalize_text(left)
    right = normalize_text(right)
    if not left and not right:
        return 100.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_character != right_character),
                )
            )
        previous = current
    distance = previous[-1]
    return round(100 * (1 - distance / max(len(left), len(right))), 2)


def _birth_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None


def identity_values(values):
    return {
        "first_name": normalize_text(values.get("first_name")),
        "middle_name": normalize_text(values.get("middle_name")),
        "last_name": normalize_text(values.get("last_name")),
        "extension_name": normalize_suffix(values.get("extension_name")),
        "birth_date": str(_birth_date(values.get("birth_date")) or ""),
        "barangay": normalize_text(values.get("barangay")),
        "valid_id_type": normalize_text(values.get("valid_id_type")),
        "valid_id_number": normalize_text(values.get("valid_id_number")).replace(" ", ""),
    }


def identity_fingerprint(values):
    payload = json.dumps(identity_values(values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate_queryset(values, *, exclude_pk=None):
    identity = identity_values(values)
    first = identity["first_name"]
    last = identity["last_name"]
    barangay = str(values.get("barangay") or "").strip()
    birth = _birth_date(values.get("birth_date"))
    filters = Q()
    if len(first) >= 2:
        filters |= Q(first_name__istartswith=first[:2])
    if len(last) >= 2:
        filters |= Q(last_name__istartswith=last[:2])
    if barangay:
        filters |= Q(barangay__iexact=barangay)
    if birth:
        filters |= Q(birth_date=birth)
    valid_id_type = str(values.get("valid_id_type") or "").strip()
    valid_id_number = str(values.get("valid_id_number") or "").strip()
    if valid_id_type and valid_id_number:
        filters |= Q(
            valid_id_type__iexact=valid_id_type,
            valid_id_number__iexact=valid_id_number,
        )
    if not filters:
        return Farmer.objects.none()
    queryset = Farmer.objects.filter(is_active=True).filter(filters)
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.only(
        "pk", "first_name", "middle_name", "last_name", "extension_name",
        "birth_date", "barangay", "valid_id_type", "valid_id_number",
    ).order_by("pk")[:MAX_DATABASE_CANDIDATES]


def _score(values, candidate):
    identity = identity_values(values)
    candidate_identity = identity_values(
        {
            "first_name": candidate.first_name,
            "middle_name": candidate.middle_name,
            "last_name": candidate.last_name,
            "extension_name": candidate.extension_name,
            "birth_date": candidate.birth_date,
            "barangay": candidate.barangay,
            "valid_id_type": candidate.valid_id_type,
            "valid_id_number": candidate.valid_id_number,
        }
    )
    first = _similarity(identity["first_name"], candidate_identity["first_name"])
    last = _similarity(identity["last_name"], candidate_identity["last_name"])
    new_full = " ".join(filter(None, (
        identity["first_name"], identity["middle_name"], identity["last_name"],
        identity["extension_name"],
    )))
    old_full = " ".join(filter(None, (
        candidate_identity["first_name"], candidate_identity["middle_name"],
        candidate_identity["last_name"], candidate_identity["extension_name"],
    )))
    full = _similarity(new_full, old_full)
    if identity["middle_name"] and candidate_identity["middle_name"]:
        middle = _similarity(identity["middle_name"], candidate_identity["middle_name"])
    else:
        middle = 60.0
    birth_same = bool(identity["birth_date"] and identity["birth_date"] == candidate_identity["birth_date"])
    barangay_same = bool(identity["barangay"] and identity["barangay"] == candidate_identity["barangay"])
    suffix_same = identity["extension_name"] == candidate_identity["extension_name"]
    id_same = bool(
        identity["valid_id_type"]
        and identity["valid_id_number"]
        and identity["valid_id_type"] == candidate_identity["valid_id_type"]
        and identity["valid_id_number"] == candidate_identity["valid_id_number"]
    )
    score = (
        first * 0.25 + last * 0.30 + full * 0.15 + middle * 0.08
        + (100 if birth_same else 0) * 0.12
        + (100 if barangay_same else 0) * 0.07
        + (100 if suffix_same else 0) * 0.03
    )
    if id_same:
        score = 100.0
    reasons = []
    if id_same:
        reasons.append("Same identification record")
    if birth_same:
        reasons.append("Same birthdate")
    if barangay_same:
        reasons.append("Same barangay")
    if first >= 85:
        reasons.append("Very similar first name")
    if last >= 85:
        reasons.append("Very similar last name")
    if full >= 85:
        reasons.append("Very similar full name")
    if not identity["middle_name"] or not candidate_identity["middle_name"]:
        reasons.append("Middle name missing from one record")
    return round(score, 1), reasons


def find_possible_duplicates(values, *, exclude_pk=None):
    matches = []
    for candidate in _candidate_queryset(values, exclude_pk=exclude_pk):
        score, reasons = _score(values, candidate)
        if score >= FLAG_THRESHOLD:
            matches.append(
                {
                    "farmer": candidate,
                    "score": score,
                    "reasons": reasons[:4],
                }
            )
    return sorted(matches, key=lambda match: (-match["score"], match["farmer"].pk))[
        :MAX_REVIEW_MATCHES
    ]


def build_review_token(values, matches, reason):
    return signing.dumps(
        {
            "fingerprint": identity_fingerprint(values),
            "candidate_ids": [match["farmer"].pk for match in matches],
            "decision": "SEPARATE",
            "reason": str(reason or "").strip()[:300],
        },
        salt=REVIEW_SALT,
        compress=True,
    )


def read_review_token(token, values, matches):
    try:
        payload = signing.loads(
            token, salt=REVIEW_SALT, max_age=REVIEW_MAX_AGE_SECONDS
        )
    except signing.BadSignature:
        return None
    expected_ids = [match["farmer"].pk for match in matches]
    if (
        payload.get("fingerprint") != identity_fingerprint(values)
        or payload.get("candidate_ids") != expected_ids
        or payload.get("decision") != "SEPARATE"
        or len(str(payload.get("reason") or "").strip()) < 5
    ):
        return None
    return payload
