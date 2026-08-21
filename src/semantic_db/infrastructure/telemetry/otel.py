from collections.abc import Iterator, Mapping
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

# Every root span is named `cli.command`, so `span.name` alone would collapse search, add
# and create into one series. `command` is promoted to a metric dimension to split them;
# it is the only one, because it is the only attribute with a closed set of values —
# `collection` or `query` as a label would be unbounded cardinality in Prometheus.
METRIC_DIMENSIONS = ("command",)


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
        labels = _metric_labels(name, attributes)
        with self._tracer.start_as_current_span(name, attributes=dict(qualify(attributes))) as span:
            try:
                yield OtelSpan(span)
            except BaseException as exc:
                # Observation only: the exception leaves exactly as it arrived, so exit
                # codes and Rich messages are unchanged by instrumentation.
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                self._errors.add(1, {**labels, "error.type": type(exc).__name__})
                raise
            finally:
                self._duration.record((perf_counter() - started) * 1000, labels)


def _metric_labels(name: str, attributes: Mapping[str, AttrValue]) -> dict[str, AttrValue]:
    """The span's identity as metric labels. Unqualified: these are label names, not OTel
    span attributes, and Prometheus reads them straight."""
    labels: dict[str, AttrValue] = {"span.name": name}
    labels.update(
        (dimension, attributes[dimension])
        for dimension in METRIC_DIMENSIONS
        if dimension in attributes
    )
    return labels
