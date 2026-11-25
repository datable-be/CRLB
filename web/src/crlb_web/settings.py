"""Settings of the validation interface; paths and secrets come from environment variables.

CRLB_DB       the crlb.sqlite to review (default data/poc/crlb_review.sqlite);
              Django keeps its own tables (users, sessions) in the same file
CRLB_PDFS     the pdfs.sqlite with the PDFs (default: pdfs.sqlite next to CRLB_DB)
CRLB_WEB_DIR  page image cache and secret key (default data/web)
CRLB_WEB_SECRET_KEY, CRLB_WEB_DEBUG (1 or 0), CRLB_WEB_HOSTS (comma-separated)
"""

import os
import secrets
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

CRLB_DB = Path(os.environ.get("CRLB_DB", REPO / "data/poc/crlb_review.sqlite"))
CRLB_PDFS = Path(os.environ.get("CRLB_PDFS", CRLB_DB.parent / "pdfs.sqlite"))
WEB_DIR = Path(os.environ.get("CRLB_WEB_DIR", REPO / "data/web"))
PAGE_CACHE = WEB_DIR / "pages"


def secret_key() -> str:
    """Return the secret key from the environment, or from a key file in WEB_DIR made on first use."""
    if key := os.environ.get("CRLB_WEB_SECRET_KEY"):
        return key
    path = WEB_DIR / "secret_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(50), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = secret_key()
DEBUG = os.environ.get("CRLB_WEB_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("CRLB_WEB_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crlb_web.validation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "crlb_web.urls"
WSGI_APPLICATION = "crlb_web.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# One SQLite file shared with crlb: WAL so readers never wait for a writer,
# IMMEDIATE transactions so concurrent writers queue instead of failing
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": CRLB_DB,
        "OPTIONS": {
            "transaction_mode": "IMMEDIATE",
            "timeout": 5,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "entries"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en"
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = WEB_DIR / "static"
