"""Temporary compatibility backend for local MariaDB 10.4 installations.

Django 5.2 supports MariaDB 10.5 and newer. MariaDB 10.4 remains adequate for
the FMIS query set, but Django blocks it during connection initialization. This
backend removes only that version gate; all normal Django MySQL behavior stays
unchanged. Upgrade the database server and remove this backend for production.
"""

import warnings

from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper
from django.db.backends.mysql.features import DatabaseFeatures as MySQLDatabaseFeatures


class DatabaseFeatures(MySQLDatabaseFeatures):
    """Remove MariaDB 10.5+ INSERT ... RETURNING assumptions."""

    can_return_columns_from_insert = False
    can_return_rows_from_bulk_insert = False


class DatabaseWrapper(MySQLDatabaseWrapper):
    """Allow the project's local legacy MariaDB server to connect."""

    features_class = DatabaseFeatures

    def check_database_version_supported(self):
        version = self.get_database_version()
        if self.features.minimum_database_version > version:
            warnings.warn(
                "MariaDB 10.4 is running in legacy compatibility mode. "
                "Upgrade to MariaDB 10.5 or newer before production use.",
                RuntimeWarning,
                stacklevel=2,
            )
