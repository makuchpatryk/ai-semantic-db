from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

# The fourth port (PRD 9.1): it earns its place because it ships with a second
# implementation — NullTelemetry, the default — and tests need the seam. It stays
# framework-free so the application layer keeps its import contract.

type AttrValue = str | int | float | bool


class SpanScope(Protocol):
    """A span that is already open. Attributes only known mid-operation — a hit count,
    a distance spread — are set through here."""

    def set(self, **attributes: AttrValue) -> None: ...


class Telemetry(Protocol):
    def span(self, name: str, **attributes: AttrValue) -> AbstractContextManager[SpanScope]: ...


NAMESPACE = "semantic_db"


def qualify(attributes: Mapping[str, AttrValue]) -> dict[str, AttrValue]:
    """Turn Pythonic keywords into namespaced OTel attribute names: `distance_min=0.1`
    becomes `semantic_db.distance.min`. Call sites stay readable; the wire format stays
    conventional. Implementations that export call this; NullTelemetry never does."""
    return {f"{NAMESPACE}.{name.replace('_', '.')}": value for name, value in attributes.items()}


class NullSpan:
    def set(self, **attributes: AttrValue) -> None:
        return None


class NullTelemetry:
    """The default. Builds no providers, starts no threads, makes no network calls."""

    @contextmanager
    def span(self, name: str, **attributes: AttrValue) -> Iterator[SpanScope]:
        yield NullSpan()
