import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-development-key-change-me")
ALLOWED_HOSTS = [
    host for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host
]

if not DEBUG and (SECRET_KEY == "unsafe-development-key-change-me" or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY to a unique value of at least 50 characters in production."
    )
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS before starting FMIS in production.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.common",
    "apps.authentication",
    "apps.dashboard",
    "apps.accounts",
    "apps.farmers",
    "apps.farm_parcels",
    "apps.crops",
    "apps.service_catalog",
    "apps.service_requests",
    "apps.interventions.apps.InterventionsConfig",
    "apps.reports",
    "apps.activity_logs",
    "apps.notifications",
    "apps.settings_page",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.common.middleware.SessionTimeoutMiddleware",
    "apps.common.middleware.PrivateUserPageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.SecurityHeadersMiddleware",
    "apps.activity_logs.middleware.ActivityLogMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "libraries": {
                "pagination_tags": "apps.common.templatetags.pagination_tags",
            },
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.settings_page.context_processors.user_preference",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASE_ENGINE = os.getenv("DB_ENGINE", "sqlite").lower()
DB_CONN_MAX_AGE = max(
    0,
    int(os.getenv("DB_CONN_MAX_AGE", "60" if not DEBUG else "0")),
)

if not DEBUG and DATABASE_ENGINE != "mysql":
    raise ImproperlyConfigured("Production FMIS requires DB_ENGINE=mysql.")

if DATABASE_ENGINE == "mysql":
    mysql_engine = (
        "apps.common.db_backends.mysql_legacy"
        if os.getenv("MYSQL_ALLOW_LEGACY_MARIADB", "False").lower() == "true"
        else "django.db.backends.mysql"
    )
    DATABASES = {
        "default": {
            "ENGINE": mysql_engine,
            "NAME": os.getenv("MYSQL_DATABASE"),
            "USER": os.getenv("MYSQL_USER"),
            "PASSWORD": os.getenv("MYSQL_PASSWORD"),
            "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "CONN_MAX_AGE": DB_CONN_MAX_AGE,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"},
        }
    }
else:
    DATABASES = {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
WHITENOISE_MAX_AGE = 31_536_000 if not DEBUG else 0
# Keep source copies on Windows. Some vendored font URLs contain query hashes,
# which are valid URLs but invalid Windows filenames during WhiteNoise cleanup.
WHITENOISE_KEEP_ONLY_HASHED_FILES = False
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "authentication.CustomUser"
LOGIN_URL = "authentication:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "authentication:landing"
# Cache only explicitly decorated public pages. Authenticated screens remain
# private and uncached. A zero timeout keeps local development changes instant.
PUBLIC_PAGE_CACHE_SECONDS = max(
    0,
    int(os.getenv("PUBLIC_PAGE_CACHE_SECONDS", "300" if not DEBUG else "0")),
)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "FMIS <noreply@fmis.local>")
STATIC_ROOT = BASE_DIR / "staticfiles"
BACKUP_ROOT = Path(os.getenv("FMIS_BACKUP_ROOT", BASE_DIR / "backups"))
FMIS_MIN_FREE_DISK_GB = max(1, int(os.getenv("FMIS_MIN_FREE_DISK_GB", "5")))
FMIS_BACKUP_ENCRYPTION_KEY = os.getenv("FMIS_BACKUP_ENCRYPTION_KEY", "")
BACKUP_AZURE_CONTAINER_URL = os.getenv("BACKUP_AZURE_CONTAINER_URL", "")
BACKUP_RCLONE_REMOTE = os.getenv("BACKUP_RCLONE_REMOTE", "").strip()
RCLONE_PATH = os.getenv("RCLONE_PATH", "").strip()
MARIADB_DUMP_PATH = os.getenv("MARIADB_DUMP_PATH", "")
FMIS_BACKUP_SCHEDULER_CONFIGURED = os.getenv(
    "FMIS_BACKUP_SCHEDULER_CONFIGURED", "False"
).lower() == "true"
FMIS_RELEASE_VERSION = os.getenv("FMIS_RELEASE_VERSION", "Unreleased build")
FMIS_FIELD_BASE_URL = os.getenv("FMIS_FIELD_BASE_URL", "").strip().rstrip("/")
if not DEBUG and FMIS_FIELD_BASE_URL and not FMIS_FIELD_BASE_URL.startswith("https://"):
    raise ImproperlyConfigured("FMIS_FIELD_BASE_URL must use HTTPS in production.")
SESSION_COOKIE_NAME = "fmis_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
REMEMBER_LOGIN_DAYS = max(1, int(os.getenv("REMEMBER_LOGIN_DAYS", "7")))
REMEMBER_LOGIN_SECONDS = REMEMBER_LOGIN_DAYS * 24 * 60 * 60
FMIS_REQUIRE_MFA = os.getenv("FMIS_REQUIRE_MFA", "True").lower() == "true"
FMIS_TRUSTED_DEVICE_DAYS = max(
    1, min(90, int(os.getenv("FMIS_TRUSTED_DEVICE_DAYS", "30")))
)
if not DEBUG and not FMIS_REQUIRE_MFA:
    raise ImproperlyConfigured("Production FMIS requires FMIS_REQUIRE_MFA=True.")
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
csrf_origins = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
CSRF_TRUSTED_ORIGINS = [origin for origin in csrf_origins.split(",") if origin]
if os.getenv("DJANGO_BEHIND_HTTPS_PROXY", "False").lower() == "true":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
if os.getenv("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
    EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() == "true"
    EMAIL_TIMEOUT = max(1, int(os.getenv("EMAIL_TIMEOUT", "15")))
    if EMAIL_USE_TLS and EMAIL_USE_SSL:
        raise ImproperlyConfigured("EMAIL_USE_TLS and EMAIL_USE_SSL cannot both be enabled.")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

if not DEBUG and not os.getenv("EMAIL_HOST"):
    raise ImproperlyConfigured(
        "Production FMIS requires EMAIL_HOST so activation and password recovery can operate."
    )

LOG_LEVEL = os.getenv("FMIS_LOG_LEVEL", "INFO").upper()
LOG_ROOT = Path(os.getenv("FMIS_LOG_ROOT", BASE_DIR / "logs"))
log_handlers = {
    "console": {
        "class": "logging.StreamHandler",
        "formatter": "standard",
    }
}
if not DEBUG:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_handlers["application_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_ROOT / "fmis-application.log",
        "maxBytes": 10 * 1024 * 1024,
        "backupCount": 14,
        "formatter": "standard",
        "encoding": "utf-8",
    }

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": log_handlers,
    "root": {
        "handlers": list(log_handlers),
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django.security": {
            "handlers": list(log_handlers),
            "level": "WARNING",
            "propagate": False,
        },
    },
}
