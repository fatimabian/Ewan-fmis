from dataclasses import dataclass

from django.utils.dateparse import parse_date


@dataclass(frozen=True)
class DateRangeFilter:
    start: object = None
    end: object = None
    error: str = ""


def parse_inclusive_date_range(params, *, label="date"):
    """Parse a safe inclusive GET date range without applying partial invalid input."""
    raw_start = params.get("date_from", "").strip()
    raw_end = params.get("date_to", "").strip()
    start = parse_date(raw_start) if raw_start else None
    end = parse_date(raw_end) if raw_end else None
    if (raw_start and start is None) or (raw_end and end is None):
        return DateRangeFilter(error=f"Enter valid {label} dates.")
    if start and end and start > end:
        return DateRangeFilter(error="From date must be on or before To date.")
    return DateRangeFilter(start=start, end=end)
