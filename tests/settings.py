SECRET_KEY = "test-only-not-secret"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_approve",
    "tests",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
