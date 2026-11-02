from django.db import models


class OcrDailyUsage(models.Model):
    """Counts provider requests per local day so the free-tier cap is respected."""

    date = models.DateField(unique=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.date}: {self.count}"
