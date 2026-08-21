from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter

from opentelemetry.metrics import MeterProvider
from opentelemetry.trace import Span, Status, StatusCode, TracerProvider

from semantic_db.application.telemetry import AttrValue, SpanScope, qualify

INSTRUMENTATION_SCOPE = "semantic_db"

# Prometheus names these `semantic_db_span_duration_milliseconds` and
# `semantic_db_errors_total`: the OTLP translation replaces dots with underscores,
# expands the `ms` unit, and appends `_total` to counters.
DURATION_INSTRUMENT = "semantic_db.span.duration"
ERRORS_INSTRUMENT = "semantic_db.errors"


class OtelSpan:
    def __init__(self, span: Span) -> None:
        self._span = span

    def set(self, **attributes: AttrValue) -> None:
        self._span.set_attributes(dict(qualify(attributes)))


class OtelTelemetry:
    """Traces every span and derives its metrics from the same call (plan D7): one port
    method, no second instrument API to drift out of sync with what is traced."""

    def __init__(self, tracer_provider: TracerProvider, meter_provider: MeterProvider) -> None:
        self._tracer = tracer_provider.get_tracer(INSTRUMENTATION_SCOPE)
        meter = meter_provider.get_meter(INSTRUMENTATION_SCOPE)
        self._duration = meter.create_histogram(
            DURATION_INSTRUMENT, unit="ms", description="Duration of a semantic-db span"
        )
        self._errors = meter.create_counter(
            ERRORS_INSTRUMENT, unit="1", description="Failed semantic-db operations"
        )

    @contextmanager
    def span(self, name: str, **attributes: AttrValue) -> Iterator[SpanScope]:
        started = perf_counter()
        with self._tracer.start_as_current_span(name, attributes=dict(qualify(attributes))) as span:
            try:
                yield OtelSpan(span)
            except BaseException as exc:
                # Observation only: the exception leaves exactly as it arrived, so exit
                # codes and Rich messages are unchanged by instrumentation.
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._errors.add(1, {"span.name": name, "error.type": type(exc).__name__})
                raise
            finally:
                self._duration.record((perf_counter() - started) * 1000, {"span.name": name})
