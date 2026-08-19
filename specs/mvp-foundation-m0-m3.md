# semantic-db MVP Foundation (M0–M3) — Implementation Plan

**Source PRD:** `PRD.md` v1.0 · **Covers:** milestones M0–M3 · **Status:** awaiting approval

## Summary

Stand up the skeleton and the write path of `semantic-db`: layered project structure, Postgres 17 + pgvector via Compose, Alembic migrations, Typer CLI, the schema domain model, `collection create` (flag + interactive), the renderer, `OllamaEmbeddingProvider`, and `record add` with embed-on-save. At the end of M3 a record is stored with its vector — but nothing reads it back yet; `search` is M5 and out of scope here.

This is the half of the PRD where all the load-bearing decisions live: field-type model, rendering, payload coercion, and the layer boundaries. Everything M4–M9 hangs off these without changing them.

## Success Criteria

1. `semantic-db --help` lists `collection create` and `record add`; exit code 0.
2. `semantic-db collection create products --field "title:string:embed,required" --field "description:text:embed" --field "category:enum(pumps|motors|valves|sensors):embed" --field "year:int:embed" --field "price:float:embed:unit=PLN"` writes one row to `collections` with a validated `schema` JSONB and prints the render preview.
3. `semantic-db collection create products` with no flags runs the questionary wizard, shows the same preview, and produces a byte-identical `schema` JSONB to criterion 2.
4. `semantic-db record add products --set "title=Hydraulic pump HP-400" --set "category=pumps" --set "year=2019" --set "price=4200" --set "description=..."` writes `records` + `embeddings` in one transaction; `embeddings.vec` has 1024 dims and `embeddings.model = "bge-m3"`.
5. `--set "year=abc"` fails with exit code 2 and a message naming both field and declared type; nothing is written.
6. `make check` is green: `ruff check`, `ruff format --check`, `mypy --strict src tests`, `lint-imports` (4 contracts), `pytest -m "not integration"`.
7. `pytest -m integration` is green against `pgvector/pgvector:pg17` via testcontainers, and `alembic check` reports no pending model changes.
8. Second-collection smoke (R1): a `books` collection (`author:string:embed,required`, `published:date:embed`, `genres:array<string>:embed`) accepts a record with no code change.

## Scope & Constraints

**In scope (M0–M3, PRD §12):**
- M0 — Compose (Postgres+pgvector), Alembic, settings, Typer skeleton, layer structure, `.importlinter`, local gate runner.
- M1 — schema domain model + validation, `collection create` flag path, persistence.
- M2 — interactive wizard over the *same* use case, with render preview.
- M3 — renderer, `OllamaEmbeddingProvider`, `record add` flag path, embed on save.

**Out of scope (later milestones, do not build):** interactive `record add` + add-another loop (M4), `search` (M5), `list`/`show` (M6), `delete` (M7), `record edit` (M8), `collection edit` (M9), and everything in PRD §3 / §13. `application/queries.py` is not created yet — it has no reader.

**Decisions taken in grilling (deviations from PRD noted):**
- **No `.github/workflows/ci.yml`.** PRD §11 / M0 called for it; user deferred CI. Mitigation for R6: the `.importlinter` contract file and a `Makefile` running all five gates locally land in M0 anyway, so layering is still enforced by a command, not a diagram. Adding `ci.yml` later is a copy of the Makefile targets.
- **Ollama runs on the host** at `http://localhost:11434` (verified running, v0.20.2). Compose ships Postgres only — no GPU passthrough, no duplicated model volume. `bge-m3` is **not currently pulled** (host has `nomic-embed-text` 768d, wrong dim) → `ollama pull bge-m3` is an explicit M0 step.
- **Demo domain: `products`** (PRD §4/§5 examples verbatim). **Fixture language: English.**

**Hard constraints:** Python 3.12 · `uv` · SQLAlchemy 2.0 async · Pydantic v2 · mypy `--strict` on `src` *and* `tests` · nothing in `domain`/`application` imports SQLAlchemy, Typer, httpx, or questionary · `halfvec(1024)` fixed to `bge-m3`.

**Trade-offs:** correctness of the write path over surface area — an unreadable corpus at the end of M3 is acceptable because M5 is one query away, whereas a wrong `schema` JSONB shape or a stale-vector path is expensive to unpick after records exist.

---

## Architecture & Design

### High-Level Flow

```
record add --set k=v
        │
   cli/commands/record.py ── parse --set → dict[str, str]
        │  asyncio.run(...)
        ▼
   AddRecord.execute(cmd)                       [application]
        │
        ├─ collections.get(name) ──────────────► SqlCollectionRepository  [infra]
        │      └─ Collection(schema=CollectionSchema)          [domain]
        │
        ├─ coerce_payload(schema, raw) ────────► domain/validation.py  (pure)
        │      └─ PayloadValidationError(field, declared_type, value)
        │
        ├─ render(schema, payload) ────────────► domain/rendering.py   (pure)
        │      └─ "Title: Hydraulic pump HP-400\nCategory: pumps\n…"
        │
        ├─ embedder.embed([rendered]) ─────────► OllamaEmbeddingProvider [infra]
        │      └─ POST /api/embed  → list[float] (len 1024)
        │
        └─ records.add(collection_id, record, vec)
               └─ one transaction: INSERT records; INSERT embeddings
```

Dependency direction: `cli → container → application → domain`, with `infrastructure` implementing `application/ports.py` and wired only in `container.py`.

### Package Layout

```
semantic-db/
├── pyproject.toml                 # uv, ruff, mypy, pytest config
├── Makefile                       # up/down/migrate/check/test-integration
├── docker-compose.yml             # postgres 17 + pgvector only
├── .importlinter                  # 4 contracts
├── .env.example
├── alembic.ini
├── src/semantic_db/
│   ├── __init__.py
│   ├── settings.py                # pydantic-settings
│   ├── container.py               # composition root
│   ├── domain/
│   │   ├── field_types.py         # FieldType enum
│   │   ├── collection.py          # FieldDefinition, CollectionSchema, Collection
│   │   ├── record.py              # Record, ScoredRecord
│   │   ├── rendering.py           # render(schema, payload) -> str      (pure)
│   │   ├── validation.py          # coerce_payload(schema, raw) -> dict (pure)
│   │   └── errors.py              # domain exception hierarchy
│   ├── application/
│   │   ├── ports.py               # EmbeddingProvider, CollectionRepository, RecordRepository
│   │   └── use_cases/
│   │       ├── create_collection.py
│   │       └── add_record.py
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── base.py            # DeclarativeBase
│   │   │   ├── models.py          # CollectionModel, RecordModel, EmbeddingModel
│   │   │   ├── session.py         # engine + async_sessionmaker
│   │   │   └── migrations/        # alembic env.py + versions/
│   │   ├── mappers.py             # ORM ⇄ domain
│   │   ├── repositories.py        # SqlCollectionRepository, SqlRecordRepository
│   │   └── ollama.py              # OllamaEmbeddingProvider
│   └── cli/
│       ├── main.py                # typer app + sub-apps
│       ├── runner.py              # asyncio.run bridge
│       ├── field_spec.py          # --field grammar parser
│       ├── set_spec.py            # --set k=v parser
│       ├── prompts.py             # questionary wizard (M2)
│       ├── render_preview.py      # Rich preview panel
│       └── commands/
│           ├── collection.py      # create
│           └── record.py          # add
└── tests/
    ├── conftest.py
    ├── fakes.py                   # InMemory repos, FakeEmbeddingProvider
    ├── unit/domain/…
    ├── unit/application/…
    ├── unit/cli/…
    └── integration/…              # @pytest.mark.integration
```

### Domain

```python
# domain/field_types.py
class FieldType(StrEnum):
    STRING = "string"; TEXT = "text"; ENUM = "enum"; INT = "int"
    FLOAT = "float"; BOOL = "bool"; DATE = "date"; ARRAY_STRING = "array<string>"

# domain/collection.py  (pydantic v2, frozen)
class FieldDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str                      # ^[a-z][a-z0-9_]*$, ≤63 chars
    type: FieldType
    embed: bool = False
    required: bool = False
    enum_values: tuple[str, ...] | None = None   # iff type is ENUM, non-empty, unique
    unit: str | None = None                      # FLOAT/INT only

    @property
    def label(self) -> str:        # "unit_price" -> "Unit price"
        return self.name.replace("_", " ").capitalize()

class CollectionSchema(BaseModel):
    model_config = ConfigDict(frozen=True)
    fields: tuple[FieldDefinition, ...]
    # validators: non-empty; names unique; ≥1 field with embed=True

class Collection(BaseModel):
    id: int | None = None
    name: str                      # ^[a-z][a-z0-9_-]*$, unique
    schema: CollectionSchema
```

Model validators raise `SchemaError` (wrapping pydantic's `ValidationError` at the boundary) so the CLI never prints a pydantic traceback.

`ScoredRecord` is declared now (`record: Record; score: float`) and left unused until M5 — it costs three lines and keeps `ports.py` matching PRD §9.1 verbatim, so M5 adds no port churn.

**Rendering** (`domain/rendering.py`, pure, no I/O):

```python
def render(schema: CollectionSchema, payload: Mapping[str, object]) -> str:
    lines = []
    for f in schema.fields:
        if not f.embed:                       # embed:false omitted entirely
            continue
        value = payload.get(f.name)
        if value is None or value == "" or value == []:   # absent optional omitted
            continue
        lines.append(f"{f.label}: {format_value(f, value)}")
    return "\n".join(lines)
```

`format_value` per type: `bool → "yes"/"no"` · `date → date.isoformat()` · `array<string> → ", ".join(v)` · `float → trim trailing ".0"` then `f"{n} {unit}"` when a unit is declared (`4200.0 → "4200 PLN"`, matching PRD §4.3) · everything else `str(v)`. Declaration order is render order — the field order in `--field`/wizard *is* the card layout, which is why the preview matters.

**Validation / coercion** (`domain/validation.py`, pure):

```python
def coerce_payload(schema, raw: Mapping[str, object]) -> dict[str, object]
```
Accepts both raw strings (flag path) and already-typed values (wizard, M4). Per field: unknown keys → `UnknownFieldError`; missing + `required` → `MissingRequiredFieldError`; missing + optional → omitted from the result (not stored as `null`); present → per-type coercer. Coercers: `int(str)`, `float(str)`, `date.fromisoformat`, `bool` from `{y,yes,true,1}/{n,no,false,0}`, `array<string>` from comma-split + strip + drop empties, `enum` membership check listing the allowed values. Every failure raises `PayloadValidationError(field=…, declared_type=…, value=…)`, rendered by the CLI as:

```
Error: field 'year' expects int, got 'abc'
```

### CLI grammar

`--field` — `name:type[:flags][:key=value]…` (PRD §4.2):
- Split on `:` — safe, because `enum(a|b|c)` contains no colon. Segment 0 = name, segment 1 = type, remaining segments are either a comma-separated flag list (`embed`, `required`) or `key=value` (`unit=PLN`).
- `enum(...)` in the type segment yields `type=enum` + `enum_values`; bare `enum` without parens is an error naming the expected form.
- Unknown flag / unknown key / unknown type → error listing valid values. Parser lives in `cli/`, returns `FieldDefinition`, and is unit-tested table-style with ~20 cases including every malformed shape.

`--set` — `key=value`, split on the **first** `=` only, so `--set "note=a=b"` works. Repeatable. Duplicate key → error.

**Flag path is non-interactive**: when any `--field` (resp. `--set`) is given, no prompt and no confirmation is shown — that is what makes fixtures and tests possible. With no flags, the wizard runs and ends in the confirm prompt.

### Interactive wizard (M2)

`cli/prompts.py` drives questionary: field name (empty ⏎ ends the loop) → type select → enum values when type is enum → unit when type is float → `embed`/`required` checkbox (`embed` pre-checked). It builds the same `list[FieldDefinition]` the parser builds and calls the same `CreateCollection` use case — the wizard is an input adapter, never a second code path. Preview + `[y/N]` confirm before the use case runs.

`questionary` is import-guarded to `cli/` by the import-linter contract, so no domain or use-case code can grow a prompt.

### Application

```python
# application/ports.py — Protocols exactly as PRD §9.1 (three ports, no fourth)

# use_cases/create_collection.py
@dataclass(frozen=True)
class CreateCollectionCommand:
    name: str
    fields: Sequence[FieldDefinition]

class CreateCollection:
    def __init__(self, collections: CollectionRepository) -> None: ...
    async def execute(self, cmd: CreateCollectionCommand) -> Collection:
        # build CollectionSchema (validates), reject duplicate name, persist

# use_cases/add_record.py
@dataclass(frozen=True)
class AddRecordCommand:
    collection_name: str
    values: Mapping[str, object]

class AddRecord:
    def __init__(self, collections, records, embedder) -> None: ...
    async def execute(self, cmd: AddRecordCommand) -> Record:
        # get collection (404 → CollectionNotFoundError)
        # coerce_payload → render → embedder.embed([rendered]) → records.add(…, vec)
```

`AddRecord` asserts `len(vec) == embedder.dim` before writing — a dimension mismatch (wrong model pulled) must fail loudly at the boundary, not as an opaque pgvector insert error.

### Storage

DDL exactly as PRD §8 — `collections`, `records`, `embeddings(record_id PK, model, halfvec(1024))`, HNSW cosine index, both FKs `ON DELETE CASCADE`. One Alembic revision `0001_initial`, with `CREATE EXTENSION IF NOT EXISTS vector` as its first op and `op.execute` for the HNSW index. Downgrade drops the three tables and leaves the extension.

SQLAlchemy models mirror the DDL with `Mapped[…]`, `JSONB`, and `pgvector.sqlalchemy.HALFVEC(1024)`. `records.payload` stores only the *coerced* payload; `date` values are serialised ISO on the way in and parsed on the way out by `mappers.py` — JSONB has no date type, and the mapper is the single place that knows it.

`SqlRecordRepository.add` opens one `session.begin()`, flushes the record to get its id, inserts the embedding row, commits. The transaction boundary lives in the repository, not the use case — the use case stays free of session semantics.

### Config

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://semantic:semantic@localhost:5432/semantic_db"
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    model_config = SettingsConfigDict(env_prefix="SEMANTIC_DB_", env_file=".env")
```

`OllamaEmbeddingProvider` calls `POST {base}/api/embed` with `{"model": …, "input": texts}` (the batch endpoint; `/api/embeddings` is the legacy single-text one) and reads `response["embeddings"]`. 60s timeout, one retry on connect error, and a dedicated `EmbeddingUnavailableError` whose CLI message says which URL failed and suggests `ollama serve` / `ollama pull bge-m3` — the single most likely first-run failure on this machine.

### Layering enforcement (`.importlinter`)

1. **Layers** (`domain` ← `application` ← `infrastructure`/`cli`, `container` on top).
2. `domain` forbidden from `sqlalchemy`, `typer`, `httpx`, `questionary`, `rich`, `alembic`, `pydantic_settings`.
3. `application` forbidden from the same set.
4. `cli` forbidden from `semantic_db.infrastructure` — everything wires through `container`.

Contract 4 is the one that rots first; it is what stops `record add` from reaching for a session directly when M4 gets fiddly.

### Alternative Approaches Considered

| Decision | Chosen | Rejected | Why |
|---|---|---|---|
| Payload validation | Explicit per-type coercer functions | Dynamically-built pydantic model per collection schema | Dynamic models produce pydantic-shaped errors that must be re-mapped to field+declared-type anyway (criterion 5), and `mypy --strict` cannot see through `create_model`. Explicit coercers are ~60 lines and directly testable. |
| Async style | Async everywhere, `asyncio.run` bridge in `cli/runner.py` | Sync SQLAlchemy + sync httpx | PRD §9.1 ports are async and M5's search plus M9's batch re-embed both benefit. Typer has no async command support, so one bridge function is the entire cost. |
| Preview rendering | Real `render()` with `<field>` placeholders on the schema preview, real values on the record preview | A separate preview formatter | A preview that isn't the production renderer is a preview of nothing (PRD §4.2's stated purpose). |
| Record identity | `BIGSERIAL id` only | `external_id` now | PRD §8 defers it to the eval harness; adding it later is one migration. |
| Ollama location | Host `localhost:11434` | Compose service | Host Ollama already runs here with GPU access; a Compose copy re-downloads bge-m3 into a volume for no benefit. |
| Missing optional values | Omitted from `payload` JSONB | Stored as `null` | Keeps `render()`'s skip rule and the JSONB shape agreeing, and makes "was never set" one state instead of two. |

---

## Implementation Steps

**M0 — skeleton**
1. `uv init`; `pyproject.toml` with deps (`typer`, `rich`, `questionary`, `pydantic`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `pgvector`, `alembic`, `httpx`) and dev deps (`pytest`, `pytest-asyncio`, `testcontainers[postgres]`, `ruff`, `mypy`, `import-linter`); ruff + mypy-strict + pytest marker config in the same file.
2. `docker-compose.yml` — `pgvector/pgvector:pg17`, named volume, healthcheck; `.env.example`.
3. `ollama pull bge-m3` and record it in the README prerequisites (host has `nomic-embed-text` only — wrong dim, would fail criterion 4).
4. Create the full package tree from §Package Layout with `__init__.py` and empty modules, so the import contracts have something to bind to.
5. `settings.py` + `infrastructure/db/session.py` (engine, `async_sessionmaker`).
6. Alembic init (async template), `env.py` reading `Settings.database_url`, revision `0001_initial` with the PRD §8 DDL.
7. `.importlinter` with the four contracts; `Makefile` targets `up`, `down`, `migrate`, `check`, `test-integration`.
8. `cli/main.py` — `app`, `collection` and `record` sub-apps, `--version`; `cli/runner.py`. Register the console script `semantic-db` in `pyproject.toml`.
9. Verify: `make up && make migrate && semantic-db --help && make check`.

**M1 — schema model + `collection create` (flags)**
10. `domain/field_types.py`, `domain/errors.py`.
11. `domain/collection.py` — `FieldDefinition`, `CollectionSchema`, `Collection` + validators.
12. `domain/rendering.py` — `render` + `format_value` (needed by M1's preview, before any embedding exists).
13. Unit tests: one per validator rejection, one per type in `format_value`, plus the `products` card from PRD §4.3 as a golden string.
14. `application/ports.py` — the three Protocols.
15. `use_cases/create_collection.py` + `tests/fakes.py` (`InMemoryCollectionRepository`) + use-case tests (happy path, duplicate name).
16. `infrastructure/db/models.py`, `mappers.py`, `repositories.py::SqlCollectionRepository`.
17. `cli/field_spec.py` parser + table-driven unit tests.
18. `container.py` composition root; `cli/commands/collection.py::create` flag path; `cli/render_preview.py` printing the schema preview with `<field>` placeholders.
19. Integration test: create via `CliRunner` against testcontainers Postgres; assert the `schema` JSONB shape.

**M2 — interactive wizard**
20. `cli/prompts.py` — field loop, type select, enum/unit follow-ups, embed/required checkbox.
21. Wire the no-flags branch of `collection create`: wizard → preview → `[y/N]` → same use case.
22. Test: wizard functions unit-tested with questionary patched; assert the produced `list[FieldDefinition]` equals the flag-parsed one for the `products` schema (criterion 3).

**M3 — embedding + `record add` (flags)**
23. `domain/record.py` — `Record`, `ScoredRecord`.
24. `domain/validation.py` — `coerce_payload` + per-type coercers; unit tests covering every type's success and failure, required-missing, unknown field, bad enum value.
25. `infrastructure/ollama.py` — `OllamaEmbeddingProvider`, dim check, `EmbeddingUnavailableError`.
26. `repositories.py::SqlRecordRepository.add` — record + embedding in one transaction.
27. `use_cases/add_record.py` + `FakeEmbeddingProvider` (deterministic 1024-dim vector from a hash of the text) + use-case tests, including the dim-mismatch guard.
28. `cli/set_spec.py` + `cli/commands/record.py::add` flag path; success line `✓ saved, embedded with bge-m3 (412ms)`.
29. Integration tests: real Ollama + testcontainers Postgres — record round-trips with a 1024-dim vector; `--set "year=abc"` writes nothing and exits 2.
30. R1 smoke: `books` collection + one record, as an integration test, not a manual step.
31. README — quickstart, the JSONB trade-off (PRD §8), the CQRS-lite note (PRD §7.5), and the deferred-CI note.

### Risks & Mitigations

- **Wrong embedding model pulled** — host currently has `nomic-embed-text` (768d); a silent 768-dim insert into `halfvec(1024)` fails deep in asyncpg.
  - Dim assertion in `AddRecord` before the write, naming expected vs actual.
  - `ollama pull bge-m3` in step 3 + README prerequisites; startup error suggests it by name.
- **Schema abstraction only fits `products` (PRD R1)** — the `books` integration test at step 30, *before* M4/M5 build on it. `array<string>` and `date` appear only in `books`, which is exactly why it can't be deferred to a manual check.
- **JSONB payload ⇄ typed domain drift** — `date` has no JSONB representation, so a value can round-trip as `str` and render differently after a reload.
  - All conversion confined to `mappers.py`; an integration test asserts `render(schema, loaded.payload) == stored.rendered` after a fresh session read.
- **Wizard and flag path diverge** (two ways to build a schema) — criterion 3 asserts byte-identical `schema` JSONB from both; the wizard is forbidden from constructing `Collection` itself.
- **Layer erosion while CI is deferred (PRD R6)** — `.importlinter` + `make check` land in M0 step 7, before any use case exists; step 9 gates M0 on it being green. `make check` is a documented pre-commit habit until `ci.yml` arrives.
- **Alembic vs models drift** — `alembic check` runs inside `make test-integration`, not only in the (absent) CI job.

## Test Strategy

| Layer | Style | Postgres | Covers |
|---|---|---|---|
| `domain` | pure unit | no | validators, every `format_value` type, every coercer success/failure, golden `products` card |
| `application` | use cases vs fakes | no | create happy/duplicate, add happy, missing-required, unknown-field, dim mismatch, collection-not-found |
| `cli` | `CliRunner`, flag path only | no | `--field` and `--set` grammar tables, exit codes (0 / 2), error text naming field + type |
| `cli` (wizard) | questionary patched | no | wizard output == flag output for `products` |
| `infrastructure` | testcontainers | yes | migration up/down, collection round-trip, record+embedding transaction, `books` smoke, real Ollama call |

Markers: `pytest -m "not integration"` is the fast gate; `@pytest.mark.integration` covers everything touching Postgres or Ollama. `pytest-asyncio` in `asyncio_mode = "auto"`. Both local testcontainers and any future CI service container read `DATABASE_URL`, so test code never branches (PRD §11).

Manual pass at the end of M3: run the wizard by hand for `products`, add three records, and read `records.rendered` in `psql` — it must be the card the preview showed.

## Success Checklist

- [ ] All 8 success criteria verified with commands and output pasted
- [ ] `make check` green (lint, format, mypy strict, 4 import contracts, unit tests)
- [ ] `make test-integration` green, `alembic check` clean
- [ ] `books` R1 smoke passes with no code change
- [ ] README documents prerequisites (`ollama pull bge-m3`), quickstart, JSONB trade-off, deferred CI
- [ ] No `application/queries.py`, no search, no list/show/edit/delete — scope held

## Timeline & Estimates

| Phase | Est. |
|---|---|
| M0 skeleton, Compose, Alembic, contracts | 4–5 h |
| M1 domain + flag `collection create` + repo | 6–8 h |
| M2 wizard | 3–4 h |
| M3 renderer wiring, Ollama, `record add`, transaction | 6–8 h |
| Integration tests + README | 3–4 h |
| **Total** | **~22–29 h** |

## Open Questions

- [ ] `record add` success line quotes elapsed embed time (PRD §5.1). Keep it on the flag path too, or only in the M4 interactive loop? *(Assumed: both — it's one `perf_counter` and it makes R3 measurable from day one.)*
- [ ] Collection name charset: `^[a-z][a-z0-9_-]*$` assumed (hyphens allowed, since it's never an identifier in DDL). Confirm at review, cheap to widen, expensive to narrow later.