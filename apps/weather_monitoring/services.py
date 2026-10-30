import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.activity_logs.services import record_event
from apps.farm_parcels.coordinate_services import parse_coordinates
from apps.farm_parcels.models import FarmParcel
from apps.farm_parcels.views import is_within_rosario
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest
from .models import (
    WeatherCoverageArea,
    WeatherEventRequest,
    WeatherMonitoringRule,
    WeatherObservation,
    WeatherRiskEvent,
    WeatherRiskParcel,
)


SOURCE_LABEL = "Open-Meteo Best Match archived forecast estimate"


class WeatherAPIError(RuntimeError):
    pass


def _source_url():
    return "https://open-meteo.com/en/docs"


def fetch_completed_day_rainfall(area, start_date, end_date, *, session=None):
    """Fetch only completed local calendar days; never treat today as completed."""
    if end_date >= timezone.localdate():
        raise WeatherAPIError("Weather monitoring can only retrieve completed days.")
    client = session or requests.Session()
    params = {
        "latitude": str(area.latitude),
        "longitude": str(area.longitude),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": "precipitation_sum",
        "timezone": "Asia/Manila",
        "forecast_days": 0,
    }
    if settings.FMIS_WEATHER_API_KEY:
        params["apikey"] = settings.FMIS_WEATHER_API_KEY
    last_error = None
    for attempt in range(3):
        try:
            response = client.get(settings.FMIS_WEATHER_API_URL, params=params, timeout=(3.05, 12))
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise WeatherAPIError(str(payload.get("reason") or "Weather API error"))
            daily = payload.get("daily") or {}
            dates = daily.get("time") or []
            rainfall = daily.get("precipitation_sum") or []
            if len(dates) != len(rainfall) or not dates:
                raise WeatherAPIError("Weather API returned incomplete daily rainfall data.")
            rows = []
            for day_text, value in zip(dates, rainfall):
                if value is None:
                    raise WeatherAPIError(f"Rainfall is missing for {day_text}.")
                try:
                    amount = Decimal(str(value)).quantize(Decimal("0.01"))
                except (InvalidOperation, TypeError):
                    raise WeatherAPIError(f"Rainfall is invalid for {day_text}.")
                if amount < 0:
                    raise WeatherAPIError(f"Rainfall is negative for {day_text}.")
                rows.append((day_text, amount))
            return {
                "rows": rows,
                "resolved_latitude": Decimal(str(payload["latitude"])),
                "resolved_longitude": Decimal(str(payload["longitude"])),
            }
        except (requests.RequestException, ValueError, KeyError, WeatherAPIError) as exc:
            last_error = exc
            if attempt == 2:
                break
    raise WeatherAPIError(f"Open-Meteo request failed after 3 attempts: {last_error}")


def store_observations(area, payload):
    saved = 0
    retrieved_at = timezone.now()
    for day_text, rainfall in payload["rows"]:
        _observation, created = WeatherObservation.objects.update_or_create(
            coverage_area=area,
            observed_date=day_text,
            defaults={
                "precipitation_mm": rainfall,
                "source": SOURCE_LABEL,
                "source_url": _source_url(),
                "retrieved_at": retrieved_at,
                "resolved_latitude": payload["resolved_latitude"],
                "resolved_longitude": payload["resolved_longitude"],
                "is_complete": True,
            },
        )
        saved += int(created)
    return saved


def haversine_km(lat1, lon1, lat2, lon2):
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _eligible_parcels(area):
    matched = []
    excluded = 0
    rows = FarmParcel.objects.filter(is_active=True, farmer__is_active=True).select_related("farmer").prefetch_related("crops")
    for parcel in rows.iterator(chunk_size=500):
        point = parse_coordinates(parcel.coordinates)
        if (
            not point
            or not is_within_rosario(*point)
            or (parcel.remarks or "").startswith("FMIS-DEMO-DATA:")
        ):
            excluded += 1
            continue
        distance = haversine_km(float(area.latitude), float(area.longitude), *point)
        if distance <= float(area.radius_km):
            crops = [
                {"crop": crop.crop_type, "variety": crop.variety}
                for crop in parcel.crops.all()
                if crop.is_active
            ]
            matched.append((parcel, Decimal(str(round(distance, 2))), crops))
    return matched, excluded


@transaction.atomic
def evaluate_rule(rule, *, period_end=None):
    period_end = period_end or timezone.localdate() - timedelta(days=1)
    period_start = period_end - timedelta(days=rule.consecutive_days - 1)
    observations = list(
        WeatherObservation.objects.filter(
            coverage_area=rule.coverage_area,
            observed_date__range=(period_start, period_end),
            is_complete=True,
        ).order_by("observed_date")
    )
    expected_dates = [period_start + timedelta(days=offset) for offset in range(rule.consecutive_days)]
    if [item.observed_date for item in observations] != expected_dates:
        return None, False
    daily_threshold = Decimal(str(rule.minimum_daily_rainfall_mm))
    accumulated_threshold = Decimal(str(rule.accumulated_rainfall_mm))
    if any(item.precipitation_mm < daily_threshold for item in observations):
        return None, False
    total = sum((item.precipitation_mm for item in observations), Decimal("0"))
    if total < accumulated_threshold:
        return None, False
    cooldown_start = period_end - timedelta(days=rule.cooldown_days)
    if WeatherRiskEvent.objects.filter(
        rule=rule, coverage_area=rule.coverage_area, period_end__gte=cooldown_start
    ).exclude(period_start=period_start, period_end=period_end).exists():
        return None, False
    event, created = WeatherRiskEvent.objects.get_or_create(
        rule=rule,
        coverage_area=rule.coverage_area,
        period_start=period_start,
        period_end=period_end,
        defaults={
            "accumulated_rainfall_mm": total,
            "suggested_priority": rule.suggested_priority,
            "recommended_action": rule.recommended_action,
        },
    )
    if created:
        matched, excluded = _eligible_parcels(rule.coverage_area)
        WeatherRiskParcel.objects.bulk_create(
            [
                WeatherRiskParcel(event=event, parcel=parcel, distance_km=distance, crop_summary=crops)
                for parcel, distance, crops in matched
            ],
            ignore_conflicts=True,
            batch_size=500,
        )
        event.excluded_parcel_count = excluded
        event.save(update_fields=["excluded_parcel_count"])
    return event, created


@transaction.atomic
def approve_event(event, *, reviewer, assigned_to, scheduled_for=None, reason=""):
    event = WeatherRiskEvent.objects.select_for_update().get(pk=event.pk)
    if event.status != WeatherRiskEvent.STATUS_DRAFT:
        return event
    service, _created = ServiceCatalog.objects.get_or_create(
        code="CROP-MONITOR",
        defaults={
            "name": "Crop Monitoring Support",
            "category": "Technical Services",
            "description": "Field monitoring support following a reviewed area alert.",
            "processing_time": "Subject to staff scheduling",
            "is_active": True,
        },
    )
    parcel_links = event.parcel_links.select_related("parcel").all()
    by_barangay = defaultdict(list)
    for link in parcel_links:
        by_barangay[link.parcel.barangay].append(link.parcel_id)
    for barangay, parcel_ids in by_barangay.items():
        request = ServiceRequest.objects.create(
            source=ServiceRequest.SOURCE_WEATHER,
            scope="BARANGAY",
            target_barangay=barangay,
            service=service,
            subject="Crop Monitoring Support",
            priority=event.suggested_priority,
            status="PENDING",
            assigned_to=assigned_to,
            notes=(
                f"Weather review {event.event_id}; {event.period_start:%b %d, %Y} to "
                f"{event.period_end:%b %d, %Y}; {event.accumulated_rainfall_mm} mm model-estimated "
                f"precipitation; {len(parcel_ids)} potentially exposed parcel(s). Exposure is not "
                f"proof of crop damage. {event.recommended_action}"
            ),
        )
        WeatherEventRequest.objects.create(event=event, service_request=request, barangay=barangay)
    event.status = WeatherRiskEvent.STATUS_APPROVED
    event.reviewed_by = reviewer
    event.reviewed_at = timezone.now()
    event.review_reason = reason.strip()
    event.assigned_to = assigned_to
    event.scheduled_for = scheduled_for
    event.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_reason", "assigned_to", "scheduled_for"])
    return event


@transaction.atomic
def dismiss_event(event, *, reviewer, reason):
    event = WeatherRiskEvent.objects.select_for_update().get(pk=event.pk)
    if event.status == WeatherRiskEvent.STATUS_DRAFT:
        event.status = WeatherRiskEvent.STATUS_DISMISSED
        event.reviewed_by = reviewer
        event.reviewed_at = timezone.now()
        event.review_reason = reason.strip()
        event.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_reason"])
    return event
