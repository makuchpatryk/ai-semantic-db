# semantic-db — OpenTelemetry + Grafana LGTM — Implementation Plan

**Source PRD:** `PRD.md` v1.0 (no telemetry section yet — this plan adds §16) · **Covers:** observability milestone M-Obs · **Builds on:** `specs/m4-m5-interactive-add-and-search.md` (shipped) · **Status:** awaiting approval

## Summary

`semantic-db` has no observability today. PRD R3 asserts "~400ms embedding is tolerable" with nothing measuring it, and the only timing that exists is a `perf_counter()` printed by `record add` (`src/semantic_db/cli/commands/record.py:52`). This milestone instruments the three hot paths — embed, vector search, record write — with OpenTelemetry traces, metrics and logs, exported over OTLP/HTTP to a self-hosted `grafana/otel-lgtm` container.

Telemetry is **off by default**. Nothing leaves the machine, ever: the exporter targets `localhost:4318`, and the backend is one Docker container next to the Postgres the project already runs. This keeps the README's "fully local — no APIs, no cloud" promise intact.

## Success Criteria

1. `SEMANTIC_DB_TELEMETRY_ENABLED=false` (the default) means **zero** OTel providers built, zero exporter threads, zero network calls, and no measurable startup cost — asserted by a unit test that the container wires `NullTelemetry`.
2. With telemetry enabled and `make obs-up` running, `semantic-db search products "quiet pump"` produces one trace in Grafana Explore with the span tree `cli.command` → `use_case.search_records` → {`embed`, `db.search`}, plus auto-instrumented HTTP and SQL child spans.
3. The `embed` span carries `semantic_db.embedding.model`, `semantic_db.embedding.dim` and `semantic_db.text.chars`; the `use_case.search_records` span carries `semantic_db.collection`, `semantic_db.k`, `semantic_db.hits`, `semantic_db.distance.min` and `semantic_db.distance.mean`, and the full query text in `semantic_db.query`.
4. Prometheus (via Grafana) shows `semantic_db_span_duration_milliseconds` histogram bucketed by `span.name`, and `semantic_db_errors_total` incrementing by `error.type` when a command exits 2.
5. Loki shows the `semantic_db` logger's records for the same run, each carrying the trace ID of its command so a log line links back to its trace.
6. A failed run — Ollama down — still exits 2 with the existing Rich message, still exports its trace with the span marked `ERROR`, and never prints an OTel exporter warning over the Rich output.
7. `make check` green (ruff, ruff format, mypy --strict, import contracts, unit tests). Two new import contracts hold: neither `domain` nor `application` imports `opentelemetry`.
8. `pytest -m integration` green in CI with a `grafana/otel-lgtm` service container: the new test flushes a real trace and finds it by trace ID via the Tempo API within 15s.

## Scope & Constraints

**In scope**
- `Telemetry` port in `application/`, `NullTelemetry` default, `OtelTelemetry` in `infrastructure/`.
- Traces, metrics and logs — all three signals, OTLP/HTTP, one endpoint.
- Auto-instrumentation for SQLAlchemy (SQL spans) and httpx (Ollama call spans).
- `grafana/otel-lgtm` as a `docker-compose` profile plus `make obs-up` / `make obs-down`.
- `otel-lgtm` service container in the CI integration job + a test that asserts a trace really lands.
- README "Observability" section, PRD §16, `.env.example` entries.

**Out of scope**
- The Postgres `searches` / `search_hits` tables. Deliberately deferred — the eval harness (PRD §13 roadmap #1) owns that, and it needs durable rows, not 14-day trace retention. Separate plan.
- Grafana Cloud or any hosted backend. Off-machine export contradicts PRD §1.
- Dashboards-as-code. Grafana Explore is enough at this size; a provisioned dashboard is a follow-up.
- eBPF / OBI auto-instrumentation in the LGTM image.
- Sampling configuration. Always-on for a single-user CLI.

**Hard constraints**
- Telemetry must never change command exit codes, stdout/stderr content, or failure behaviour. Instrumentation is observation only.
- `mypy --strict` and the four existing import contracts stay green.
- Ports 4317/4318/3000/3200 must not collide with Postgres 5432 or Ollama 11434 — they don't.

**Decisions taken in grilling**

| # | Decision | Consequence |
|---|---|---|
| D1 | **OTel/Grafana only; no Postgres search log** | This milestone buys latency insight, not retrieval quality. Eval data is a separate, durable store. |
| D2 | **OTel packages are core dependencies**, not an extra | Every install carries them. No conditional import, no `ImportError` branch to test. Cost: ~6 direct + ~6 transitive packages, including `requests` (see A2). |
| D3 | **Full query text in span attributes** | `semantic_db.query` is verbatim. Safe because export is `localhost`-only and the corpus is the user's own. Revisit if a remote exporter is ever offered. |
| D4 | **CI runs `otel-lgtm` as a service container** | Integration test proves the whole export path, not just span shape. Cost: extra CI service + a readiness poll. |
| D5 | **Off unless `SEMANTIC_DB_TELEMETRY_ENABLED=true`** | Default install pays nothing and never warns about an absent collector. Opt in explicitly. |
| D6 | **Traces + metrics + logs** | Full use of the LGTM stack. Logs are the weakest leg — see R1. |
| D7 | **Metrics derive from spans, not from a second port method** | `OtelTelemetry.span()` records a duration histogram and, on failure, an error counter. One port method; metrics come free; no parallel instrument API to keep in sync. |

---

## Architecture & Design

### High-Level Flow

```
semantic-db search products "quiet pump"
  │
  ├── cli/runner.py:run()  ──►  telemetry.span("cli.command", command="search")
  │       │
  │       └── container.py  builds Telemetry ONCE (Null or Otel), injects into use cases,
  │                         instruments the SQLAlchemy engine + httpx, and on exit
  │                         force_flush()es every provider before the process dies
  │
  ├── SearchRecords.execute()  ──►  span("use_case.search_records", collection=…, k=…)
  │       ├── embed_one()      ──►  span("embed", model=…, dim=…, chars=…)
  │       │      └── httpx auto-instrumentation ──► span "POST /api/embed"
  │       └── records.search() ──►  span("db.search", collection_id=…, k=…)
  │              └── sqlalchemy auto-instrumentation ──► span "SELECT records"
  │
  └── OTLP/HTTP :4318 ──► otel-lgtm ──► Tempo (traces) / Prometheus (metrics) / Loki (logs)
                                            └── Grafana :3000
```

### Key Changes

**`src/semantic_db/application/telemetry.py`** (new) — the port. Framework-free, so the layer contracts hold.

```python
type AttrValue = str | int | float | bool

class SpanScope(Protocol):
    def set(self, **attributes: AttrValue) -> None: ...

class Telemetry(Protocol):
    def span(self, name: str, **attributes: AttrValue) -> AbstractContextManager[SpanScope]: ...

class NullSpan:  # set() is a no-op
class NullTelemetry:  # span() yields NullSpan, costs one contextmanager frame
```

One method. Attributes discovered mid-operation (hit count, distance stats) go through `scope.set(...)`. PRD §9.1 says a port needs a second implementation or a test seam — this has both: `NullTelemetry` ships, `RecordingTelemetry` tests.

**`src/semantic_db/infrastructure/telemetry/providers.py`** (new) — builds and owns the SDK.
- `Resource(service.name="semantic-db", service.version=__version__)`.
- `TracerProvider` + `BatchSpanProcessor(OTLPSpanExporter)`.
- `MeterProvider` + `PeriodicExportingMetricReader(OTLPMetricExporter)`.
- `LoggerProvider` + `BatchLogRecordProcessor(OTLPLogExporter)`, attached to the `semantic_db` logger.
- Silences `logging.getLogger("opentelemetry")` to CRITICAL so a dead collector never prints over Rich (criterion 6).
- `shutdown()` force-flushes all three with a 2s timeout.

**`src/semantic_db/infrastructure/telemetry/otel.py`** (new) — `OtelTelemetry` implements the port. Its `span()` contextmanager:
1. starts a span, sets attributes,
2. on exception: `record_exception`, `set_status(ERROR)`, bump `semantic_db_errors_total{error.type=…}`, re-raise unchanged,
3. always: record elapsed ms into `semantic_db_span_duration_milliseconds{span.name=…}`.

That step 3 is D7 — metrics are a byproduct of tracing, no second API.

**`src/semantic_db/container.py`** — the only place that wires. Builds `NullTelemetry` or `OtelTelemetry`, calls `SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)` and `HTTPXClientInstrumentor().instrument()` when enabled, injects `telemetry` into all three use cases, and in the `finally` block calls `providers.shutdown()` **before** `engine.dispose()`.

**Use cases** — `AddRecord`, `SearchRecords`, `CreateCollection` take `telemetry: Telemetry` as a constructor argument and wrap `execute()` in one span. `application/embedding.py:embed_one` takes `telemetry` too and owns the `embed` span, so both callers get it without duplication.

**`src/semantic_db/cli/runner.py`** — `run()` opens the `cli.command` root span. Command name comes from a new parameter (`run(main, command="search")`) rather than frame inspection. The existing `except SemanticDbError` branch stays byte-identical; the span records the error on the way out.

**`src/semantic_db/settings.py`** — two fields:
```python
telemetry_enabled: bool = False
otlp_endpoint: str = "http://localhost:4318"
```

**`docker-compose.yml`** — new service behind a profile so `make up` stays Postgres-only:
```yaml
  otel-lgtm:
    image: grafana/otel-lgtm:<pinned-tag>
    profiles: ["obs"]
    ports: ["3000:3000", "4317:4317", "4318:4318", "3200:3200"]
    volumes: [lgtmdata:/data]
```
3200 is exposed because the integration test queries Tempo directly.

**`Makefile`** — `obs-up: docker compose --profile obs up -d otel-lgtm`, `obs-down`.

**`.github/workflows/ci.yml`** — the `integration` job gains the `otel-lgtm` service. The image ships no healthcheck, so readiness is a poll step in the same shape as the existing Ollama loop:
```bash
for _ in $(seq 1 60); do curl -sf http://localhost:3200/ready && exit 0; sleep 1; done
```

**`.importlinter`** — add `opentelemetry` to the `forbidden_modules` of both the `domain-is-framework-free` and `application-is-framework-free` contracts. The port must stay pure.

**Dependencies** (core, per D2):
```
opentelemetry-api>=1.44
opentelemetry-sdk>=1.44
opentelemetry-exporter-otlp-proto-http>=1.44
opentelemetry-instrumentation-sqlalchemy>=0.65b0
opentelemetry-instrumentation-httpx>=0.65b0
opentelemetry-instrumentation-logging>=0.65b0
```

### Alternative Approaches Considered

**A1 — Backend: `grafana/otel-lgtm` vs SigNoz vs Jaeger vs Grafana Cloud**
- *otel-lgtm* (chosen): one container, all three signals, Apache-2.0 image wrapping AGPLv3 components, no account, no key. Grafana labels it dev/demo/test — which is exactly a laptop CLI. AGPL obligations don't trigger: stock image, unmodified, not offered over a network, not redistributed.
- *SigNoz*: 4GB RAM hard minimum, ~1.5–2GB idle. Too heavy sitting next to Postgres and a 1.2GB embedding model.
- *Jaeger v2 all-in-one*: lightest, native OTLP — but traces only, and D6 wants metrics and logs.
- *Grafana Cloud free*: genuinely free and permanent (10k series, 50GB traces, 14-day retention, no card) — rejected because data leaves the machine, contradicting the product's core claim.

**A2 — Exporter transport: OTLP/HTTP vs OTLP/gRPC**
HTTP chosen. gRPC pulls `grpcio`, a large platform-specific binary wheel that slows `uv sync` and CI on every runner. HTTP pulls `requests`, which is redundant next to the `httpx` already in the tree but is pure Python and small. Redundancy beats build weight here. Switching later is a one-line exporter swap.

**A3 — Span processor: Batch vs Simple**
`BatchSpanProcessor` + explicit `force_flush()` on container teardown. `SimpleSpanProcessor` exports synchronously per span, adding an HTTP round-trip inside the 400ms budget we are trying to measure — the instrument would distort the measurement. A CLI process is short-lived, so the flush is the load-bearing part; A3 is only safe because of it.

**A4 — Metrics: derived from spans vs explicit instruments on the port**
Derived (D7). An explicit `counter()`/`histogram()` on the port doubles the API and guarantees drift between what is traced and what is counted. Anything genuinely not span-shaped can be added later.

**A5 — Logs: stdlib `logging` bridged vs a `log()` method on the port**
Bridged. `opentelemetry-instrumentation-logging` attaches trace context to stdlib records, which is what makes criterion 5 work. A port method would need its own correlation plumbing for no gain. Application code stays log-free; the handful of log calls live in `cli/runner.py` and `infrastructure/`.

---

## Implementation Steps

1. **Deps + tooling.** Add the six packages to `[project.dependencies]`, `uv lock`, `uv sync`. Add `opentelemetry` to both framework-free contracts in `.importlinter`. Confirm `make check` still green before writing any telemetry code — this catches a mypy/`wrapt` surprise early.
2. **Port.** Write `application/telemetry.py`: `AttrValue`, `SpanScope`, `Telemetry`, `NullSpan`, `NullTelemetry`. Unit test that `NullTelemetry.span()` is a working no-op context manager and re-raises.
3. **Recording fake.** Add `RecordingTelemetry` to `tests/fakes.py`, alongside `FakeEmbeddingProvider`: captures `(name, attributes, error_type, ended)` per span so tests assert shape without an SDK.
4. **Thread the port through the application layer.** Add `telemetry` to the constructors of `AddRecord`, `SearchRecords`, `CreateCollection` and to `embed_one`. Wrap each `execute()` in its span. Set `semantic_db.hits`, `distance.min`, `distance.mean` via `scope.set()` after the repository call. Update `tests/unit/test_use_cases.py` call sites.
5. **Settings.** Add `telemetry_enabled` and `otlp_endpoint`; mirror into `.env.example`.
6. **SDK providers.** Write `infrastructure/telemetry/providers.py` — resource, three providers, exporters, OTel-logger silencing, `shutdown()` with timeout.
7. **`OtelTelemetry`.** Write `infrastructure/telemetry/otel.py` per D7 (span + duration histogram + error counter). Unit test with `InMemorySpanExporter` and `InMemoryMetricReader`: assert span name, attributes, ERROR status on raise, and that the exception propagates unchanged.
8. **Wire the container.** Branch on `settings.telemetry_enabled`; instrument SQLAlchemy and httpx only when enabled; `shutdown()` before `engine.dispose()`. Unit test asserts the default build yields `NullTelemetry` and instruments nothing.
9. **Root span in the CLI.** `run(main, command=...)` opens `cli.command`; update the four call sites in `cli/commands/`. Add the `semantic_db` logger calls (command start, command failure, embedding failure in `ollama.py`).
10. **Compose + Makefile.** Add the `obs`-profiled `otel-lgtm` service with a pinned tag and a `/data` volume; add `obs-up` / `obs-down`.
11. **Manual verification.** `make obs-up`, `SEMANTIC_DB_TELEMETRY_ENABLED=true uv run semantic-db search products "quiet pump"`, open Grafana at :3000 (`admin`/`admin`), confirm criteria 2–5 by eye. Confirm criterion 6 by stopping Ollama and re-running.
12. **Integration test.** `tests/integration/test_telemetry_otlp.py` — skip unless the endpoint answers; build a container with telemetry on; run a real search; capture the root trace ID; `force_flush()`; poll `GET :3200/api/traces/{trace_id}` for up to 15s; assert the expected span names are present.
13. **CI.** Add the `otel-lgtm` service and the readiness poll to the `integration` job.
14. **Docs.** README "Observability" section (how to turn it on, what the spans mean, the AGPL note), PRD §16 recording D1–D7, and the R3 claim updated once real numbers exist.
15. **Close the loop on R3.** Run the seed script with telemetry on, read the actual p50/p95 of the `embed` span, and write the measured number into PRD R3 in place of "~400ms".

### Risks & Mitigations

- **R1 — The OTel Python logs SDK is still experimental.** `opentelemetry.sdk._logs` is a private module with no backward-compatibility guarantee across minor releases, and `LoggingHandler` was recently deprecated in favour of `opentelemetry-instrumentation-logging`. This is the weakest part of D6.
  - *Mitigation:* every `_logs` import is confined to `providers.py` — one file to fix on a breaking release. Pin `opentelemetry-sdk` to a compatible range in `uv.lock` and treat SDK bumps as a reviewed change, not a routine one.
  - *Fallback:* if it breaks, drop to traces + metrics and let Grafana derive log-like context from span events. Criterion 5 becomes optional; nothing else in the plan depends on it.
- **R2 — `opentelemetry-instrumentation-httpx` 0.65b0 may not match `httpx>=0.28`.** Its optional `instruments-any` extra points at `httpx2>=2.0.0`, which suggests the 2.x line is the primary target.
  - *Mitigation:* step 1 verifies this before any code is written. If the instrumentation misbehaves, drop it — the hand-written `embed` span already covers the latency question, and the HTTP child span is a nicety.
- **R3 — Short-lived CLI loses spans at exit.** `BatchSpanProcessor` exports on a timer; a process that lives 400ms can die first.
  - *Mitigation:* explicit `force_flush()` in the container's `finally`, before `engine.dispose()`, with a bounded timeout so a dead collector cannot hang the CLI. This is the single most important line in the milestone and gets its own test (step 12 fails without it).
- **R4 — Exporter noise over Rich output.** A dead collector makes OTel log connection errors to stderr, corrupting the CLI's output contract (criterion 6).
  - *Mitigation:* silence the `opentelemetry` logger at provider construction. Verified manually in step 11 with the collector down.
- **R5 — CI gets slower and flakier.** A second service container plus a poll-until-found assertion is the classic flaky test.
  - *Mitigation:* pin the image tag (never `latest`); poll Tempo's `/ready` before the suite; bound the trace lookup at 15s and `pytest.skip` — not fail — when the endpoint is unreachable at all, so a local `pytest -m integration` without the container still passes.
- **R6 — Instrumentation becomes ceremony (PRD R4, restated).** Six new packages and a port for a single-user CLI is real weight.
  - *Mitigation:* one port method, one span per meaningful operation, metrics derived rather than declared. If the span tree stops earning its keep, `NullTelemetry` is already the default — deletion is a settings flip, not a refactor.

---

## Test Strategy

**Unit** (`pytest -m "not integration"`, no SDK, no container)
- `NullTelemetry.span()` is a no-op context manager and re-raises exceptions unchanged.
- Each use case opens its expected span with its expected attributes — via `RecordingTelemetry`, asserted in `tests/unit/test_use_cases.py`.
- `SearchRecords` sets `hits`, `distance.min`, `distance.mean` from real fake-repository results.
- A raising use case marks its span errored and still propagates the original exception type.
- `OtelTelemetry` against `InMemorySpanExporter` + `InMemoryMetricReader`: span name, attributes, ERROR status, duration histogram recorded, error counter incremented.
- `build_container()` with default settings yields `NullTelemetry` and leaves SQLAlchemy/httpx uninstrumented.

**Integration** (`pytest -m integration`, needs Postgres + Ollama + otel-lgtm)
- `test_telemetry_otlp.py` — real search, real flush, trace found by ID in Tempo within 15s, expected span names present. Skips cleanly if :3200 does not answer.
- The existing end-to-end suite runs with telemetry **off**, proving instrumentation changed no behaviour.

**Manual** (step 11)
- Grafana Explore: the full span tree, the histogram, the correlated log line.
- Ollama stopped: exit code 2, unchanged Rich error, no exporter noise, errored span still exported.
- `make up` without the `obs` profile: no LGTM container starts.

**Performance**
- With telemetry off, `record add` wall time is unchanged from `main` (compare the `elapsed_ms` the command already prints).
- With telemetry on, the added overhead stays under ~10ms per command — read from the `cli.command` span minus its children.

---

## Success Checklist

- [ ] All eight success criteria met, with a Grafana screenshot for 2–5
- [ ] `make check` green
- [ ] `pytest -m integration` green locally and in CI
- [ ] Six import contracts green (four existing + `opentelemetry` forbidden in domain and application)
- [ ] `uv.lock` committed; `otel-lgtm` image pinned to a tag, not `latest`
- [ ] README Observability section + PRD §16 written
- [ ] PRD R3 updated with a measured number
- [ ] Default install (telemetry off) shows no behaviour change in the existing test suite

## Timeline & Estima****tes

| Phase | Work | Estimate |
|---|---|---|
| 1 | Steps 1–5 — deps, port, fake, threading, settings | ~3h |
| 2 | Steps 6–9 — SDK providers, `OtelTelemetry`, container, CLI root span | ~3h |
| 3 | Steps 10–11 — compose, Makefile, manual verification in Grafana | ~1.5h |
| 4 | Steps 12–13 — integration test + CI service | ~2.5h |
| 5 | Steps 14–15 — docs, PRD, measured R3 number | ~1.5h |
| | **Total** | **~11.5h** plus buffer for R1/R2 |

R1 and R2 are the two places this can overrun; both are checked in step 1 before the expensive work starts.

## Open Questions

- [ ] Which `grafana/otel-lgtm` tag to pin? Resolve at step 10 by taking the current release tag rather than `latest`, so CI is reproducible.
- [ ] Does `opentelemetry-instrumentation-httpx` 0.65b0 work against `httpx>=0.28`, or is it 2.x-only? Answered empirically in step 1; R2 covers both outcomes.
