import pytest

from semantic_db.application.telemetry import NullTelemetry, Telemetry, qualify


def test_null_telemetry_is_a_working_context_manager() -> None:
    telemetry: Telemetry = NullTelemetry()

    with telemetry.span("anything", collection="products") as scope:
        scope.set(hits=3)


def test_null_telemetry_re_raises_unchanged() -> None:
    telemetry: Telemetry = NullTelemetry()

    with pytest.raises(ValueError, match="boom"), telemetry.span("anything"):
        raise ValueError("boom")


def test_qualify_namespaces_and_dots_attribute_names() -> None:
    assert qualify({"collection": "products", "distance_min": 0.25}) == {
        "semantic_db.collection": "products",
        "semantic_db.distance.min": 0.25,
    }
