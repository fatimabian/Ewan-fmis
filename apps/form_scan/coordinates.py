"""Read handwritten coordinates and propose, never apply, a correction.

Each written number is expanded into variants (as written, sign flipped, decimal
point inserted, leading digit added), the two numbers are tried in both orders,
and the cheapest combination that lands inside Rosario becomes the suggestion.
"""
import re
from dataclasses import dataclass, field
from itertools import product

from apps.common.geometry import is_in_rosario

DMS_PATTERN = re.compile(
    r"""^\s*(?P<deg>\d+(?:\.\d+)?)\s*[°º˚d]\s*
        (?:(?P<min>\d+(?:\.\d+)?)\s*['′’m]\s*)?
        (?:(?P<sec>\d+(?:\.\d+)?)\s*(?:["″”s]|''|′′|’’)\s*)?
        (?P<hem>[NSEWnsew])?\s*$""",
    re.VERBOSE,
)
PLAIN_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

FIX_LABELS = {
    "swap": "latitude and longitude appear to be swapped",
    "decimal": "a decimal point appears to be missing",
    "sign": "a minus sign appears to have been added or dropped",
    "digit": "a leading digit appears to have been dropped",
    "dms": "written in degrees, minutes, seconds",
}


@dataclass(frozen=True)
class Interpretation:
    """What was written, what it means, and the proposed correction if one is needed."""

    as_read: tuple | None
    in_rosario: bool
    suggestion: tuple | None = None
    fixes: tuple = field(default_factory=tuple)
    unreadable: bool = False

    @property
    def explanation(self):
        return "; ".join(FIX_LABELS[fix] for fix in self.fixes)


def _variants(text):
    """Return [(value, tags)] readings of one written number."""
    text = (text or "").strip()
    if not text:
        return []
    match = DMS_PATTERN.match(text)
    if match:
        value = float(match["deg"]) + float(match["min"] or 0) / 60 + float(match["sec"] or 0) / 3600
        if (match["hem"] or "").upper() in {"S", "W"}:
            value = -value
        return [(value, ("dms",))]
    text = re.sub(r"[NSEWnsew]$", "", text.replace(" ", ""))
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    if not PLAIN_PATTERN.match(text):
        return []
    value = float(text)
    variants = [(value, ())]
    variants.append((-value, ("sign",)))
    digits = text.lstrip("+-")
    integer = digits.split(".")[0]
    if "." not in digits and len(digits) >= 4:
        for places in (2, 3):
            variants.append((float(f"{digits[:places]}.{digits[places:]}"), ("decimal",)))
    if len(integer) in (1, 2):
        variants.append((float("1" + digits), ("digit",)))
    return variants


def _usable(latitude, longitude):
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def interpret(latitude_text, longitude_text):
    """Interpret the two written coordinates."""
    first, second = _variants(latitude_text), _variants(longitude_text)
    if not first or not second:
        return Interpretation(None, False, unreadable=True)
    # The first variant of each number is always the value exactly as written.
    as_read = (first[0][0], second[0][0])
    if not _usable(*as_read):
        as_read = None
    if as_read and is_in_rosario(*as_read):
        if "dms" in first[0][1] + second[0][1]:
            return Interpretation(as_read, True, as_read, ("dms",))
        return Interpretation(as_read, True)

    best = None
    for swapped in (False, True):
        left, right = (second, first) if swapped else (first, second)
        for (a, tags_a), (b, tags_b) in product(left, right):
            if not _usable(a, b) or not is_in_rosario(a, b):
                continue
            tags = tuple(dict.fromkeys(tags_a + tags_b + (("swap",) if swapped else ())))
            cost = len([tag for tag in tags if tag != "dms"])
            if best is None or cost < best[0]:
                best = (cost, (a, b), tags)
    if best:
        return Interpretation(as_read, False, best[1], best[2])
    return Interpretation(as_read, False, unreadable=as_read is None)
