"""OpenTelemetry setup. Spans use the GenAI semantic conventions so any OTLP backend — or FORGE for
FORGE-initiated runs — can interpret them. Free-text attributes go through ``redact`` where they are
set (``nova.agent.runtime``); prompts and completions are never recorded on spans."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from nova.config import get_settings
from nova.infra.redaction import RedactingFilter

_configured = False


def _headers(raw: str) -> dict[str, str]:
    result = {}
    for pair in raw.split(","):
        key, sep, value = pair.partition("=")
        if sep:
            result[key.strip()] = value.strip()
    return result


def configure_telemetry(service_name: str | None = None) -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactingFilter())
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name or settings.otel_service_name,
                "service.version": settings.version,
                "deployment.environment": settings.env,
            }
        )
    )
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint += "/v1/traces"
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=_headers(settings.otel_exporter_otlp_headers)))
        )
    trace.set_tracer_provider(provider)
    _configured = True
