import os

# no database / admin / auth needed, this just proxies a few apis

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secret")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = ["corsheaders", "planner"]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "truckroute.urls"
WSGI_APPLICATION = "truckroute.wsgi.application"
DATABASES = {}
USE_TZ = True

# cache for places / routes / weather (clients.py). locally: in memory, one process.
# hosted on vercel every request can run in a different short-lived instance, so the
# memory cache would mostly be empty. there REDIS_URL points to a hosted redis (upstash)
# that all instances share. KV_URL is the name vercel's upstash integration uses
REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("KV_URL")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}

# vite dev server. on deploy set CORS_ORIGINS to the frontend url
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

# planner logs to the console, with the trace id so a log line can be found in jaeger
LOGGING = {
    "version": 1,
    # keep django's own loggers, e.g. the "GET /api/places/ 200" request lines from runserver
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s trace=%(otelTraceID)s %(message)s"},
    },
    "filters": {"trace_id": {"()": "truckroute.telemetry.DefaultTraceId"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default", "filters": ["trace_id"]}},
    "loggers": {"planner": {"handlers": ["console"], "level": "INFO"}},
}
