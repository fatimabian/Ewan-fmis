from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.weather_monitoring.models import WeatherMonitoringRule, WeatherMonitoringRun, WeatherObservation
from apps.weather_monitoring.services import (
    WeatherAPIError,
    evaluate_rule,
    fetch_completed_day_rainfall,
    store_observations,
)


class Command(BaseCommand):
    help = "Fetch completed-day rainfall and create idempotent preliminary weather events."

    def handle(self, *args, **options):
        if not settings.FMIS_WEATHER_LICENSE_REVIEWED:
            raise CommandError(
                "Weather monitoring is disabled until FMIS_WEATHER_LICENSE_REVIEWED=True."
            )
        rules = list(
            WeatherMonitoringRule.objects.filter(
                is_active=True, is_approved=True, coverage_area__is_active=True
            ).select_related("coverage_area")
        )
        run = WeatherMonitoringRun.objects.create()
        errors = []
        try:
            areas = {rule.coverage_area_id: rule.coverage_area for rule in rules}
            yesterday = timezone.localdate() - timedelta(days=1)
            for area in areas.values():
                run.areas_checked += 1
                max_days = max(
                    rule.consecutive_days for rule in rules if rule.coverage_area_id == area.pk
                )
                start_date = yesterday - timedelta(days=max_days - 1)
                existing = set(
                    WeatherObservation.objects.filter(
                        coverage_area=area,
                        observed_date__range=(start_date, yesterday),
                        is_complete=True,
                    ).values_list("observed_date", flat=True)
                )
                expected = {start_date + timedelta(days=offset) for offset in range(max_days)}
                if existing != expected:
                    try:
                        payload = fetch_completed_day_rainfall(area, start_date, yesterday)
                        run.observations_saved += store_observations(area, payload)
                    except WeatherAPIError as exc:
                        errors.append(f"{area.code}: {exc}")
                        continue
                for rule in (item for item in rules if item.coverage_area_id == area.pk):
                    _event, created = evaluate_rule(rule, period_end=yesterday)
                    run.events_created += int(created)
            run.status = (
                WeatherMonitoringRun.STATUS_PARTIAL
                if errors and run.areas_checked > len(errors)
                else WeatherMonitoringRun.STATUS_FAILED
                if errors
                else WeatherMonitoringRun.STATUS_SUCCESS
            )
            run.error_summary = "\n".join(errors)[:2000]
            run.finished_at = timezone.now()
            run.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Checked {run.areas_checked} area(s), stored {run.observations_saved} new observation(s), "
                    f"created {run.events_created} event(s); status={run.status}."
                )
            )
        except Exception as exc:
            run.status = WeatherMonitoringRun.STATUS_FAILED
            run.error_summary = str(exc)[:2000]
            run.finished_at = timezone.now()
            run.save()
            raise
