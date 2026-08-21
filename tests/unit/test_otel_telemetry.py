"""`OtelTelemetry` against in-memory SDK exporters — no collector, no network."""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from semantic_db.infrastructure.telemetry.otel import OtelTelemetry


@pytest.fixture
def wired() -> tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    return OtelTelemetry(tracer_provider, meter_provider), exporter, reader


def metric_points(reader: InMemoryMetricReader, name: str) -> list[object]:
    data = reader.get_metrics_data()
    assert data is not None
    return [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def test_span_is_exported_with_qualified_attributes(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, _ = wired

    with telemetry.span("use_case.search_records", collection="products", k=5) as scope:
        scope.set(hits=2, distance_min=0.1)

    span: ReadableSpan = exporter.get_finished_spans()[0]
    assert span.name == "use_case.search_records"
    assert span.attributes is not None
    assert span.attributes["semantic_db.collection"] == "products"
    assert span.attributes["semantic_db.k"] == 5
    assert span.attributes["semantic_db.hits"] == 2
    assert span.attributes["semantic_db.distance.min"] == 0.1
    assert span.status.status_code is not StatusCode.ERROR


def test_a_raising_span_is_errored_and_the_exception_is_unchanged(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, _ = wired

    with pytest.raises(ValueError, match="ollama is down"), telemetry.span("embed"):
        raise ValueError("ollama is down")

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.events[0].name == "exception"


def test_span_duration_is_recorded_as_a_histogram(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, _, reader = wired

    with telemetry.span("db.search"):
        pass

    points = metric_points(reader, "semantic_db.span.duration")
    assert len(points) == 1
    point = points[0]
    assert point.attributes == {"span.name": "db.search"}  # type: ignore[attr-defined]
    assert point.count == 1  # type: ignore[attr-defined]


def test_errors_are_counted_by_type(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, _, reader = wired

    with pytest.raises(RuntimeError), telemetry.span("cli.command", command="search"):
        raise RuntimeError("nope")

    points = metric_points(reader, "semantic_db.errors")
    assert len(points) == 1
    point = points[0]
    assert point.value == 1  # type: ignore[attr-defined]
    assert point.attributes == {  # type: ignore[attr-defined]
        "span.name": "cli.command",
        "error.type": "RuntimeError",
    }


def test_a_successful_span_counts_no_error(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, _, reader = wired

    with telemetry.span("cli.command", command="search"):
        pass

    assert metric_points(reader, "semantic_db.errors") == []


def test_child_spans_nest_under_their_parent(
    wired: tuple[OtelTelemetry, InMemorySpanExporter, InMemoryMetricReader],
) -> None:
    telemetry, exporter, _ = wired

    with telemetry.span("cli.command", command="search"), telemetry.span("embed"):
        pass

    child, parent = exporter.get_finished_spans()  # children finish first
    assert child.name == "embed"
    assert child.parent is not None
    assert parent.context is not None
    assert child.parent.span_id == parent.context.span_id
