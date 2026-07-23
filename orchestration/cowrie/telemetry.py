"""OpenTelemetry wiring - SRS 2.4 names it under Observability.

Instruments FastAPI (one span per request, with route, method and status) and
SQLAlchemy (one span per query), then exports over OTLP/HTTP when a collector
is configured.

Design notes worth stating:

  * Everything here is optional at runtime. A missing collector, an unreachable
    one, or the packages not being installed all degrade to no tracing rather
    than to a service that will not boot. Observability that can take the
    system down is worse than none.

  * Health checks are excluded from tracing. A platform probes /health every
    few seconds, and those spans would swamp the ones that describe real work.

  * Spans are batched, not sent per request, so a slow collector adds latency
    to a background flush rather than to a payment.
"""

from __future__ import annotations

from .config import settings

_configured = False


def setup(app) -> str:
    """Instrument the app. Returns a short description of what was set up."""
    global _configured
    if _configured:
        return "already configured"

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        return "opentelemetry not installed; tracing disabled"

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.version,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)

    exporters: list[str] = []

    if settings.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
            )
            exporters.append(f"otlp -> {settings.otel_endpoint}")
        except Exception as exc:  # noqa: BLE001
            print(f"[otel] OTLP exporter unavailable ({exc})")

    if settings.otel_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        exporters.append("console")

    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Liveness probes would otherwise dominate the trace volume.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,health/.*")
    except Exception as exc:  # noqa: BLE001
        print(f"[otel] FastAPI instrumentation skipped ({exc})")

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from .db import engine

        SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception as exc:  # noqa: BLE001
        print(f"[otel] SQLAlchemy instrumentation skipped ({exc})")

    _configured = True
    return ", ".join(exporters) if exporters else "spans recorded, no exporter configured"
