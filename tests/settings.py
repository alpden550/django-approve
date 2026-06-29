import tempfile

SECRET_KEY = "test-only-not-secret"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

MEDIA_ROOT = tempfile.mkdtemp(prefix="django-approve-test-media-")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django_approve",
    "tests",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "DIRS": [],
        "OPTIONS": {},
    },
]

ROOT_URLCONF = "tests.urls"

USE_TZ = True
