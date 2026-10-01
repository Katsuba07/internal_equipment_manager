"""
Django settings for the Equipment Management Application (EMA).

Everything environment-specific — secret key, debug flag, allowed hosts —
comes from a .env file so this file never needs editing to deploy.
"""

import os
import sys
from pathlib import Path

from django.contrib.messages import constants as message_constants
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# Everything written to disk (database, uploads, logs) lives under data/
# so backing up means copying exactly one folder.
DATA_DIR = Path(os.getenv("EMA_DATA_DIR") or (BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool = False) -> bool:
    return (os.getenv(name) or str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in (os.getenv(name) or default).split(",") if item.strip()]


SECRET_KEY = os.getenv("EMA_SECRET_KEY", "insecure-development-key-do-not-ship")
DEBUG = _env_bool("EMA_DEBUG", False)

# "*" by default so other machines on the LAN can reach the server by IP.
# Set EMA_ALLOWED_HOSTS to a specific hostname when exposing it to the internet.
ALLOWED_HOSTS = _env_list("EMA_ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = _env_list("EMA_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third party
    "crispy_forms",
    "crispy_bootstrap5",
    "django_tables2",
    "django_filters",
    "simple_history",
    # Project apps
    "core",
    "equipment",
    "systems",
    "maintenance",
    "incidents",
    "repairs",
    "inventory",
    "calibration",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Records who made each change (django-simple-history)
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.app_info",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# SQLite in WAL mode: many readers stay unblocked while one writer commits.
# busy_timeout makes a write wait its turn instead of failing with
# "database is locked".
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "ema.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=20000;"
                "PRAGMA foreign_keys=ON;"
            ),
        },
    }
}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("EMA_TIME_ZONE", "Asia/Ho_Chi_Minh")
USE_I18N = True
USE_TZ = True

# Dates are shown as 17 Sep 2026 — unambiguous for a site where both
# day-first and month-first habits are in the room.
DATE_FORMAT = "d M Y"
DATETIME_FORMAT = "d M Y H:i"
SHORT_DATE_FORMAT = "d M Y"
DATE_INPUT_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"]
DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Deliberately NOT the "Manifest" variant: that one requires a successful
    # collectstatic before the site will serve at all, and forgetting it turns
    # every page into a 500. This still compresses, and works either way.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_MAX_AGE = 3600

MEDIA_URL = "uploads/"
MEDIA_ROOT = DATA_DIR / "uploads"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
DJANGO_TABLES2_TEMPLATE = "tables/table.html"

# Attachment size ceiling (incident photos, calibration certificates)
EMA_MAX_UPLOAD_MB = int(os.getenv("EMA_MAX_UPLOAD_MB", "20"))
DATA_UPLOAD_MAX_MEMORY_SIZE = EMA_MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Product documents live on SharePoint (the TE folder). OneDrive keeps a synced
# copy of that folder on this server; the app reads and writes that copy and
# OneDrive carries the changes to SharePoint. People open the files on
# SharePoint itself, so its permissions still apply.
EMA_DOCS_ROOT = Path(os.getenv("EMA_DOCS_ROOT")) if os.getenv("EMA_DOCS_ROOT") else None
# The test suite never touches the real SharePoint folder; tests that need one
# make their own.
if "test" in sys.argv[1:2]:
    EMA_DOCS_ROOT = None
EMA_DOCS_SHAREPOINT_SITE = os.getenv("EMA_DOCS_SHAREPOINT_SITE", "https://computimehk.sharepoint.com")
EMA_DOCS_SHAREPOINT_FOLDER = os.getenv(
    "EMA_DOCS_SHAREPOINT_FOLDER", "/sites/CTV/Shared Documents/CTV3/MP lines Prepare Setup CTVN CTV3/TE"
)
# Plant given to a product first seen as a folder on the share.
EMA_DOCS_DEFAULT_PLANT = os.getenv("EMA_DOCS_DEFAULT_PLANT", "CTV2")
# How often the Products page re-reads the synced folder, in seconds.
EMA_DOCS_RESCAN_SECONDS = int(os.getenv("EMA_DOCS_RESCAN_SECONDS", "120"))

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Django calls the error level "error"; the stylesheet calls it "danger".
MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# Hardening that only applies once real HTTPS is in front of the app.
#
# Turning these on while serving plain HTTP over the LAN locks everyone out,
# because browsers will not send "secure" cookies over http://.
if _env_bool("EMA_BEHIND_HTTPS_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # one year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_AGE = 12 * 60 * 60  # one shift
SESSION_SAVE_EVERY_REQUEST = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} [{levelname}] {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": DATA_DIR / "ema.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
}
