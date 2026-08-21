"""The export path, end to end.

Two things need proving, and they need different instruments:

* that a real CLI process — one that runs for a second and then exits — gets its spans
  out at all (plan R3). A stub OTLP receiver answers this deterministically and without a
  backend: the assertion is over the bytes the dying process actually sent.
* that the real backend accepts what we send and gives the trace back by ID.

Span shape itself is asserted by the unit tests.
"""

import asyncio
import os
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

import httpx
import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.trace import format_trace_id, get_current_span

from semantic_db.application.use_cases.add_record import AddRecordCommand
from semantic_db.application.use_cases.create_collection import CreateCollectionCommand
from semantic_db.application.use_cases.search_records import SearchRecordsCommand
from semantic_db.container import Container, build_container
from semantic_db.infrastructure.db.session_types import SessionFactory
from semantic_db.settings import Settings
from tests.schemas import PRODUCTS

pytestmark = pytest.mark.integration

TEMPO_URL = os.environ.get("SEMANTIC_DB_TEMPO_URL", "http://localhost:3200")
OTLP_ENDPOINT = os.environ.get("SEMANTIC_DB_OTLP_ENDPOINT", "http://localhost:4318")

LOOKUP_TIMEOUT_SECONDS = 15
EXPECTED_SPANS = {"cli.command", "use_case.search_records", "embed", "db.search"}

PRODUCT_VALUES = {
    "title": "Silent hydraulic pump HP-400",
    "description": "A quiet pump for indoor use",
    "category": "pumps",
    "year": "2019",
    "price": "4200",
}


class _CollectorHandler(BaseHTTPRequestHandler):
    """Accepts OTLP/HTTP exports and keeps the trace payloads."""

    received: list[ExportTraceServiceRequest] = []

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's spelling
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.endswith("/v1/traces"):
            request = ExportTraceServiceRequest()
            request.ParseFromString(body)
            type(self).received.append(request)

        payload = ExportTraceServiceResponse().SerializeToString()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass  # the stub stays as quiet as the CLI it is watching


@pytest.fixture
def stub_collector() -> Iterator[tuple[str, list[ExportTraceServiceRequest]]]:
    _CollectorHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CollectorHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _CollectorHandler.received
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def tempo() -> str:
    """A local `make obs-up` is optional, so an absent collector skips rather than fails."""
    try:
        response = httpx.get(f"{TEMPO_URL}/ready", timeout=2.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"no otel-lgtm at {TEMPO_URL} ({exc}); run `make obs-up`")
    if response.status_code != 200:
        pytest.skip(f"otel-lgtm at {TEMPO_URL} is not ready yet")
    return TEMPO_URL


async def test_a_cli_that_exits_still_exports_its_spans(
    stub_collector: tuple[str, list[ExportTraceServiceRequest]],
    database_url: str,
    session_factory: SessionFactory,
) -> None:
    endpoint, received = stub_collector
    await _seed_a_searchable_record(database_url)

    exit_code, stdout, stderr = await _run_cli(
        ["search", "products", "quiet pump"], database_url, endpoint
    )

    assert exit_code == 0, stderr
    assert "Silent hydraulic pump" in stdout
    assert stderr == "", "an exporter must never write to the CLI's own streams"

    # The process is gone; these spans left it before it died.
    assert _exported_span_names(received) >= EXPECTED_SPANS


async def test_a_real_search_is_found_in_tempo_by_trace_id(
    tempo: str, database_url: str, session_factory: SessionFactory
) -> None:
    settings = Settings(
        database_url=database_url, telemetry_enabled=True, otlp_endpoint=OTLP_ENDPOINT
    )

    async with build_container(settings) as container:
        await _seed(container)
        with container.telemetry.span("cli.command", command="search"):
            trace_id = format_trace_id(get_current_span().get_span_context().trace_id)
            result = await container.search_records.execute(
                SearchRecordsCommand("products", "quiet pump", k=10)
            )

    assert result.hits, "the search itself must work before its trace means anything"
    assert await _tempo_span_names(tempo, trace_id) >= EXPECTED_SPANS


async def _seed_a_searchable_record(database_url: str) -> None:
    """Setup runs with telemetry off: only the process under test is observed."""
    async with build_container(
        Settings(database_url=database_url, telemetry_enabled=False)
    ) as container:
        await _seed(container)


async def _seed(container: Container) -> None:
    await container.create_collection.execute(
        CreateCollectionCommand(name="products", fields=PRODUCTS.fields)
    )
    await container.add_record.execute(AddRecordCommand("products", PRODUCT_VALUES))


async def _run_cli(args: list[str], database_url: str, otlp_endpoint: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "semantic_db.cli.main",
        *args,
        env={
            **os.environ,
            "SEMANTIC_DB_DATABASE_URL": database_url,
            "SEMANTIC_DB_TELEMETRY_ENABLED": "true",
            "SEMANTIC_DB_OTLP_ENDPOINT": otlp_endpoint,
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode is not None
    return process.returncode, stdout.decode(), stderr.decode()


def _exported_span_names(received: list[ExportTraceServiceRequest]) -> set[str]:
    return {
        span.name
        for request in received
        for resource_spans in request.resource_spans
        for scope_spans in resource_spans.scope_spans
        for span in scope_spans.spans
    }


async def _tempo_span_names(tempo: str, trace_id: str) -> set[str]:
    """Poll until Tempo has ingested the trace. Bounded: a lookup that never resolves is a
    failure, not a hang. Lookup is by ID — Tempo's *search* index lags far behind ingestion."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        for _ in range(LOOKUP_TIMEOUT_SECONDS):
            response = await client.get(f"{tempo}/api/traces/{trace_id}")
            if response.status_code == 200 and response.json().get("batches"):
                return _names(response.json()["batches"])
            await asyncio.sleep(1)

    raise AssertionError(f"trace {trace_id} never arrived within {LOOKUP_TIMEOUT_SECONDS}s")


def _names(batches: list[dict[str, Any]]) -> set[str]:
    return {
        span["name"]
        for batch in batches
        for scope_spans in batch.get("scopeSpans", [])
        for span in scope_spans.get("spans", [])
    }
