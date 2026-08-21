"""The default build pays nothing for telemetry (plan D5). No Postgres needed: the
engine is created lazily and never connected here."""

from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from semantic_db.application.telemetry import NullTelemetry
from semantic_db.container import build_container
from semantic_db.settings import Settings


async def test_the_default_container_wires_null_telemetry() -> None:
    async with build_container(Settings(telemetry_enabled=False)) as container:
        assert isinstance(container.telemetry, NullTelemetry)


async def test_the_default_container_instruments_nothing() -> None:
    async with build_container(Settings(telemetry_enabled=False)):
        assert not SQLAlchemyInstrumentor().is_instrumented_by_opentelemetry
        assert not HTTPXClientInstrumentor().is_instrumented_by_opentelemetry


async def test_telemetry_is_off_unless_it_is_switched_on() -> None:
    # Read from the field defaults, not from an instance: a developer's own .env must
    # not decide whether this holds.
    assert Settings.model_fields["telemetry_enabled"].default is False
    assert Settings.model_fields["otlp_endpoint"].default == "http://localhost:4318"
