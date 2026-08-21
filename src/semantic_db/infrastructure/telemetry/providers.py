"""Builds and owns the OTel SDK. Every `opentelemetry.sdk._logs` import lives here —
the logs SDK is still private and has no cross-version guarantee, so a breaking release
is one file to fix (plan R1)."""

import logging
from dataclasses import dataclass

from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from semantic_db import __version__

SERVICE_NAME = "semantic-db"
LOGGER_NAME = "semantic_db"

# A CLI command lives for milliseconds; a flush that hangs on a dead collector would be
# worse than a lost trace. Bounded, always.
FLUSH_TIMEOUT_MS = 2000

# The exporter's own budget, and the one that actually binds: an unreachable collector is
# retried with backoff *inside* a single export call, which `force_flush`'s timeout cannot
# interrupt. Left at the 10s default, three signals turn a dead collector into a 20s CLI.
EXPORT_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class TelemetryProviders:
    """The three signal providers, plus the teardown that actually gets them exported."""

    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider
    _handler: LoggingHandler

    def shutdown(self) -> None:
        """Flush every signal before the process dies, then release the handler.

        `BatchSpanProcessor` exports on a timer that a 400ms command never reaches (plan
        R3). The SDK's own `atexit` hook would eventually flush too, but only after the
        engine is disposed and with no time limit; this flushes in the right order and
        within a bounded budget.
        """
        self.tracer_provider.force_flush(FLUSH_TIMEOUT_MS)
        self.meter_provider.force_flush(FLUSH_TIMEOUT_MS)
        self.logger_provider.force_flush(FLUSH_TIMEOUT_MS)

        logging.getLogger(LOGGER_NAME).removeHandler(self._handler)

        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def build_providers(otlp_endpoint: str) -> TelemetryProviders:
    silence_otel_logging()

    base = otlp_endpoint.rstrip("/")
    resource = Resource.create({"service.name": SERVICE_NAME, "service.version": __version__})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{base}/v1/traces", timeout=EXPORT_TIMEOUT_SECONDS)
        )
    )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{base}/v1/metrics", timeout=EXPORT_TIMEOUT_SECONDS)
            )
        ],
    )

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=f"{base}/v1/logs", timeout=EXPORT_TIMEOUT_SECONDS)
        )
    )

    # Only this project's logger is bridged, not the root one: everything else on the
    # root logger belongs to libraries and would be noise in Loki.
    handler = LoggingHandler(logger_provider=logger_provider)
    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)

    return TelemetryProviders(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        _handler=handler,
    )


def silence_otel_logging() -> None:
    """A collector that is down must not print exporter errors over the Rich output —
    the CLI's stdout/stderr contract is part of its behaviour (criterion 6)."""
    logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
    # The instrumentation handler keeps its own stream handler for internal errors.
    logging.getLogger("opentelemetry.instrumentation.logging.handler.internal").setLevel(
        logging.CRITICAL
    )
