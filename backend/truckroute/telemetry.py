# opentelemetry setup: traces for every request + every outside api call, and the
# trace id in every log line. called from manage.py and wsgi.py before django starts.
#
# traces only get sent somewhere if OTEL_EXPORTER_OTLP_ENDPOINT is set
# (locally: jaeger from docker-compose.yml, http://localhost:4318)

import logging
import os
import re
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class DefaultTraceId(logging.Filter):
    # log lines from code that didn't go through setup() (a script, a shell) have no
    # otelTraceID, and the log format in settings.py would crash on them
    def filter(self, record):
        if not hasattr(record, "otelTraceID"):
            record.otelTraceID = "-"
        return True


def name_and_hide_key(span, request):
    # tomtom key is in the url query, don't send it to the tracing backend
    url = re.sub(r"key=[^&]+", "key=REDACTED", request.url)
    span.set_attribute("http.url", url)
    span.set_attribute("url.full", url)
    # "GET api.tomtom.com" is easier to read in jaeger than just "GET"
    span.update_name(request.method + " " + urlparse(request.url).hostname)


def setup():
    provider = TracerProvider(resource=Resource.create({"service.name": "truck-weather-router"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    DjangoInstrumentor().instrument()
    RequestsInstrumentor().instrument(request_hook=name_and_hide_key)
    # adds otelTraceID to log records, used in the LOGGING format in settings.py
    LoggingInstrumentor().instrument(set_logging_format=False, inject_trace_context=True)
