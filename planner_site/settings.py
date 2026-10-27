"""Django settings. Production values come from environment variables (see .env.example)."""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """KEY=value lines from .env for local runs (Docker Compose passes the same file; real environment wins)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            if v:
                os.environ.setdefault(k.strip(), v)


_load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


# Vercel (serverless): read-only code folder, so data goes to /tmp and the database must be external (DATABASE_URL)
ON_VERCEL = bool(os.environ.get("VERCEL"))
DEBUG = env_bool("DJANGO_DEBUG", not ON_VERCEL)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key-change-me" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if ON_VERCEL:  # the project's *.vercel.app addresses (custom domains go in the variables above)
    ALLOWED_HOSTS += [".vercel.app"]
    CSRF_TRUSTED_ORIGINS += ["https://*.vercel.app"]
# Cross-site requests carry only the origin (never the page path); OpenStreetMap blocks map tiles without it.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

INSTALLED_APPS = [
    "planner",  # first, so its templates restyle the admin
    "django.contrib.admin",
    "django.contrib.humanize",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
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
    "planner.security.ContentSecurityPolicyMiddleware",
]
if ON_VERCEL:  # Vercel's CDN serves /static from public/static
    MIDDLEWARE.remove("whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "planner_site.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "planner.branding.context",
    ]},
}]
WSGI_APPLICATION = "planner_site.wsgi.application"

DATA_DIR = Path(os.environ.get("FTTH_DATA_DIR", "/tmp/archplanner" if ON_VERCEL else BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {"default": dj_database_url.config(
    default=f"sqlite:///{(DATA_DIR / 'planner.sqlite3').as_posix()}", conn_max_age=600)}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # Local SQLite: readers do not block the writer (WAL), writers queue for up to 30 s instead of failing with
    # "database is locked", and take the write lock at the start of a transaction. Production uses PostgreSQL.
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "timeout": 30, "transaction_mode": "IMMEDIATE",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"})

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", BASE_DIR / "staticfiles"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # on Vercel the CDN serves the collected files, and the function has no manifest to look names up in
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage" if not (DEBUG or ON_VERCEL)
                    else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
# Survey photos are private: served through an access-checked view, never as public media.
MEDIA_ROOT = DATA_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}

# Photo AI: survey photos are sent to a vision model only when a planner presses "Analyse" (see .env.example)
PHOTO_AI = {
    "provider": os.environ.get("PHOTO_AI_PROVIDER", "").strip().lower(),  # "roboflow" or "groq"
    "url": os.environ.get("PHOTO_AI_URL", "").strip(),
    "key": os.environ.get("PHOTO_AI_KEY", "").strip(),
    "model": os.environ.get("PHOTO_AI_MODEL", "").strip(),
}

# AI assistant chat (Groq): a question and a summary of the open project are sent only when a planner asks
AI_CHAT = {
    "key": (os.environ.get("AI_CHAT_KEY") or os.environ.get("GROQ_API_KEY")
            or (os.environ.get("PHOTO_AI_KEY", "") if PHOTO_AI["provider"] == "groq" else "")).strip(),
    "model": os.environ.get("AI_CHAT_MODEL", "openai/gpt-oss-120b").strip(),
    "url": os.environ.get("AI_CHAT_URL", "https://api.groq.com/openai/v1/chat/completions").strip(),
}
