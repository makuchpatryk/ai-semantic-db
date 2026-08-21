# semantic-db — PRD (MVP)

**Version:** 1.1
**Status:** In progress — M0–M5 shipped, M6–M9 open
**Author:** Patryk Makuch
**Last reviewed against the code:** 2026-08-20

> Earlier drafts (0.1–0.6) scoped filters, hybrid retrieval, an eval harness, and LlamaIndex. All of that moved to §12 Roadmap. This document describes an MVP of **three commands**.

> **Where the build stands:** the three core commands (`collection create`, `record add`, `search`) all work, in both the flag and the interactive path. The management commands of §7 (`list`, `show`, `edit`, `delete`) are not built yet. Per-milestone status in §12, deviations from this spec in §12.1.

---

## 1. Summary

`semantic-db` is a local CLI for **semantic search over user-defined structured records**. You define a schema in the CLI, add records against it, and search them in natural language. Postgres + pgvector for storage, Ollama for embeddings. No API keys, no cloud.

## 2. Scope

Three commands. Nothing else ships in v1.

Three core commands:

```bash
semantic-db collection create <name>     # define fields and types
semantic-db record add <collection>      # add a record
semantic-db search <collection> "query"  # semantic search
```

Plus management for both, so the tool is usable without dropping to `psql`:

```bash
semantic-db collection list | show | edit | delete
semantic-db record list | show | edit | delete
```

## 3. Non-goals

Not in the MVP: metadata filters, lexical/hybrid search, reranking, eval harness, LlamaIndex, bulk import/export, answer synthesis, web UI, HTTP API. Schema migration is deliberately partial — see §7.3. Full roadmap in §13.

---

## 4. Schema definition

### 4.1 Field types

| Type | Notes |
|---|---|
| ~~`string`~~ | **dropped as built** — collapsed into `text`; one text type, one prompt, one renderer |
| `text` | free text; multiline in the terminal (`$EDITOR` dropped as built — see §12.1) |
| `enum` | declared value list |
| `int` | |
| `float` | optional `unit` label for rendering |
| `bool` | |
| `date` | ISO |
| `array<string>` | joined with commas when rendered |

Two flags per field: `embed` (goes into the searchable text) and `required`.

There is no `filter` flag in the MVP — search is purely semantic, so nothing consumes typed predicates yet. It arrives with filters in §11, along with the per-field indexes.

### 4.2 `collection create`

```
$ semantic-db collection create products

── Field 1 ──────────────────────────────
Field name:  title
Type:        › text
                 enum
                 int
                 float
                 bool
                 date
                 array<string>
Options:     [x] embed in search text
             [x] required

── Field 2 ──────────────────────────────
Field name:  category
Type:        enum
Enum values (comma-separated): pumps, motors, valves, sensors
Options:     [x] embed in search text
             [ ] required

── Field 3 ──────────────────────────────
Field name:  ⏎  (empty to finish)

── Preview ──────────────────────────────
Title: <title>
Category: <category>
Description: <description>

Create collection 'products' with 5 fields? [y/N]
```

The preview shows the exact shape of the text that will be embedded, before anything is written. Bad rendering is the top cause of bad retrieval and the hardest thing to notice later.

A flag equivalent exists for every prompt, because tests and fixtures can't drive stdin:

```bash
semantic-db collection create products \
    --field "title:text:embed,required" \
    --field "description:text:embed" \
    --field "category:enum(pumps|motors|valves|sensors):embed" \
    --field "year:int:embed" \
    --field "price:float:embed:unit=PLN"
```

Grammar: `name:type[:flags][:key=value]` · flags `embed`, `required` · enums inline as `enum(a|b|c)`.

### 4.3 Rendering

**No chunking.** Each record renders into one labelled card, derived from the schema:

```
Title: Hydraulic pump HP-400
Category: pumps
Year: 2019
Price: 4200 PLN
Description: Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.
```

Field labels measurably improve retrieval on structured data. `embed: false` fields are omitted. This rendered string is what gets embedded, and it is stored alongside the record.

---

## 5. Adding records

### 5.1 `record add`

Prompts are generated from the schema — type, enum values, and `required` all come from the field definition, so an invalid record can't be entered in the first place.

```
$ semantic-db record add products

title *          Hydraulic pump HP-400
description      [multiline; Alt+Enter for a newline]
category         [pumps/motors/valves/sensors]  pumps
year             2019
price (PLN)      4200

── Preview ──────────────────────────────
Title: Hydraulic pump HP-400
Category: pumps
Year: 2019
Price: 4200 PLN
Description: Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.

Save? [Y/n]   ✓ saved, embedded with bge-m3 (412ms)

Add another? [Y/n]
```

| Type | Input handling |
|---|---|
| `text` | multiline terminal input — Enter submits, Alt+Enter inserts a newline |
| `enum` | prompt with tab-completion over the declared values; `(skip)` when optional |
| `int` / `float` | numeric, rejected on parse failure |
| `bool` | y/n |
| `date` | ISO, validated |
| `array<string>` | comma-separated, split per item |

**Embed on save.** A record with no vector is invisible to `search`, which is baffling right after adding it. The Ollama call is ~400ms — acceptable inline, and it keeps the mental model simple: added means searchable.

**`Add another?`** keeps the loop open. Entering enough records to make search interesting is the tedious part; the loop is what makes it survivable.

Flag equivalent:

```bash
semantic-db record add products \
    --set "title=Hydraulic pump HP-400" \
    --set "category=pumps" \
    --set "year=2019"
```

Values are coerced by declared type, not guessed. `--set "year=abc"` fails naming the field and its type.

---

## 6. Search

```bash
semantic-db search products "quiet pump for industrial use"
semantic-db search products "quiet pump" --k 5 --explain
```

Pipeline, in full:

```
query → embed (Ollama) → cosine search over pgvector → top-k
```

Output is a Rich table: rank, cosine distance, and the record's first embeddable field, with `--explain` adding the full rendered text of each hit in a panel. As built the distance is always shown rather than a derived similarity score — one number, and it is the one the index actually ranks on.

`search` refuses to run when the collection was embedded with a model other than the configured one, naming both (`EmbeddingModelMismatchError`). Comparing vectors across models silently returns plausible nonsense, which is the worst failure mode this tool has.

That's the whole thing. No fusion, no reranking, no filters. It's a small enough surface that the retrieval quality is entirely a function of the rendering and the embedding model — which is the right place for attention in v1.

---

## 7. Managing collections and records

### 7.1 Commands

```bash
semantic-db collection list                       # name, field count, record count
semantic-db collection show products              # fields, types, flags, render preview
semantic-db collection edit products              # additive only — see 7.3
semantic-db collection delete products            # cascades

semantic-db record list products [--limit 20] [--offset 0]
semantic-db record show products 42               # payload, rendered text, model used
semantic-db record edit products 42               # prompts prefilled; re-renders, re-embeds
semantic-db record delete products 42
```

Records are addressed by their numeric `id`, shown in `record list`. A stable `external_id` only becomes necessary when a golden set has to survive a reingest, so it stays deferred.

### 7.2 `record edit` re-embeds

Editing a payload without re-rendering and re-embedding leaves `payload`, `rendered`, and `vec` describing three different versions of the record — the exact drift §8 warns about, arriving through a different door. So edit is: prompt prefilled → re-render → re-embed → write all three in one transaction. Skipping the embed is not offered as a flag; a stale vector is worse than a slow command.

### 7.3 `collection edit` is a schema migration

This is the one genuinely hard command, so it is deliberately restricted in v1:

| Change | v1 | Why |
|---|---|---|
| Rename collection | allowed | metadata only |
| Add an **optional** field | allowed | existing payloads stay valid; re-render + re-embed all records |
| Toggle `embed` on a field | allowed | changes rendered text; re-render + re-embed all records |
| Add a **required** field | rejected | existing records would become invalid with no value to supply |
| Remove a field | rejected | destroys data; drop and rebuild instead |
| Change a field's type | rejected | needs a coercion strategy per type pair; not worth it at this stage |
| Add/remove enum values | add allowed, remove rejected | removal can orphan existing values |

Anything that alters the rendered text triggers a full re-embed with a progress bar. At a few hundred records that's a couple of minutes — acceptable, and the command says so before starting.

Rejected changes fail with the reason and the suggestion to `delete` and recreate. Naming the restriction explicitly is better than a half-working migration path.

### 7.4 `collection delete` cascades

`ON DELETE CASCADE` removes the records and their embeddings. The command prints what will be destroyed and requires typing the collection name to confirm:

```
$ semantic-db collection delete products
This deletes collection 'products': 5 fields, 312 records, 312 embeddings.
Type the collection name to confirm: products
✓ deleted
```

`--yes` skips the prompt for scripted use. `record delete` uses a plain y/n — losing one record is recoverable by re-entering it.

### 7.5 Layering: reads don't get use cases

Write operations carry rules — validation, re-rendering, re-embedding, cascade confirmation — and stay as use cases. Read operations apply no rules and go through a single façade instead, rather than generating eight five-line pass-through classes:

```
application/
├── ports.py
├── queries.py               # list_collections, show_collection, list_records, show_record
└── use_cases/
    ├── create_collection.py
    ├── edit_collection.py       # the schema-migration rules live here
    ├── delete_collection.py
    ├── add_record.py
    ├── edit_record.py           # re-render + re-embed
    ├── delete_record.py
    └── search_records.py
```

The split is CQRS-lite and worth stating in the README: a use case that only forwards a call to a repository is ceremony, and the layering is better served by admitting that than by keeping the shape symmetric.

---

## 8. Storage

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE collections (
    id      BIGSERIAL PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL,
    schema  JSONB NOT NULL              -- validated field definitions
);

CREATE TABLE records (
    id             BIGSERIAL PRIMARY KEY,
    collection_id  BIGINT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    payload        JSONB NOT NULL,      -- validated against collection schema
    rendered       TEXT NOT NULL        -- exact text that was embedded
);

CREATE TABLE embeddings (
    record_id  BIGINT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    vec        halfvec(1024) NOT NULL
);

CREATE INDEX embeddings_hnsw ON embeddings USING hnsw (vec halfvec_cosine_ops);
```

**Why JSONB:** a table per collection with real typed columns would be faster, but requires generating and migrating DDL per user schema, and Alembic plus user-defined DDL do not coexist peacefully. JSONB is what vector databases do for metadata and it survives arbitrary schemas. Name it as a deliberate tradeoff in the README.

**Why `rendered` is stored** rather than recomputed on read: it is the exact string that produced the vector. Recomputing it after a template change would silently drift from what the index contains.

**Deferred, one migration each:** `external_id` when the eval harness needs stable references; `model` in the embeddings PK when two models are compared; `content_hash` when re-embedding hurts; `records.tsv` with lexical search; per-field expression indexes with filters.

---

## 9. Architecture (Clean Architecture)

Dependencies point inward only. Nothing in `domain` imports SQLAlchemy, Typer, or httpx.

```
src/semantic_db/
├── domain/
│   ├── collection.py        # Collection, CollectionSchema, FieldDefinition
│   ├── field_types.py       # FieldType
│   ├── record.py            # Record, ScoredRecord, Payload
│   ├── validation.py        # coerce_value, payload validation against the schema
│   ├── errors.py            # SemanticDbError and its subtypes
│   └── rendering.py         # render(schema, payload) -> str   (pure)
│
├── application/
│   ├── ports.py             # three Protocols
│   ├── queries.py           # read-only reads, no use case each (see 7.5)
│   ├── embedding.py         # embed_one helper, shared by add_record and search
│   └── use_cases/           # built: create_collection, add_record, search_records
│       ├── create_collection.py
│       ├── edit_collection.py       # M9
│       ├── delete_collection.py     # M7
│       ├── add_record.py
│       ├── edit_record.py           # M8
│       ├── delete_record.py         # M7
│       └── search_records.py
│
├── infrastructure/
│   ├── db/                  # SQLAlchemy models, session, Alembic
│   ├── repositories.py
│   └── ollama.py            # OllamaEmbeddingProvider
│
├── cli/
│   ├── main.py
│   ├── commands/
│   └── prompts.py           # schema-driven prompt generation
│
└── container.py             # composition root — the only place that wires
```

Pydantic is permitted in `domain`: validating a payload against a declared schema *is* a domain rule here. SQLAlchemy models are separate classes in `infrastructure`, mapped to and from domain entities in the repositories.

### 9.1 Ports

```python/
from typing import Protocol

class EmbeddingProvider(Protocol):
    model_name: str
    dim: int
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class CollectionRepository(Protocol):
    async def create(self, collection: Collection) -> Collection: ...
    async def get(self, name: str) -> Collection | None: ...
    async def list(self) -> list[CollectionSummary]: ...          # M6
    async def update(self, collection: Collection) -> Collection: ...   # M9
    async def delete(self, name: str) -> None: ...                # M7

class RecordRepository(Protocol):
    async def add(self, collection_id: int, record: Record, vec: list[float]) -> Record: ...
    async def search(self, collection_id: int, vec: list[float], k: int) -> list[ScoredRecord]: ...
    async def embedding_models(self, collection_id: int) -> frozenset[str]: ...   # added as built
    async def get(self, collection_id: int, record_id: int) -> Record | None: ...       # M6
    async def list(self, collection_id: int, limit: int, offset: int) -> list[Record]: ...  # M6
    async def update(self, record: Record, vec: list[float]) -> Record: ...   # M8, atomic re-embed
    async def delete(self, collection_id: int, record_id: int) -> None: ...   # M7
```

Methods land with the milestone that needs them, so the ports carry no stubs. `embedding_models` is the one addition to this list: `search` has to fail loudly when the corpus was embedded with a model other than the configured one, instead of returning quietly meaningless distances.

**No fourth port without a second implementation or a test that needs the seam.** `EmbeddingProvider` earns its place — swapping Ollama models is a config change and the fake makes use-case tests DB-free. A `Renderer` interface would not; it's a pure function.

Enforced by an `import-linter` contract in CI from M0, so the layering is a property of the code rather than a diagram in a README.

### 9.2 Testing

| Layer | Style | Needs Postgres |
|---|---|---|
| `domain` | Pure unit tests | no |
| `application` | Use cases against fake ports | no |
| `infrastructure` | Integration, testcontainers | yes |
| `cli` | Typer `CliRunner`, flag path only | no |

---

## 10. Stack

Python 3.12 · `uv` · Postgres 17 + pgvector · SQLAlchemy 2.0 (async) + Alembic · Pydantic v2 · Typer + Rich + **prompt-toolkit** · Ollama (`bge-m3`, 1024d, multilingual) · pytest + testcontainers · ruff + mypy strict · import-linter · Docker Compose

`questionary` was the original pick and was replaced by `prompt-toolkit` directly: the wizard needs multiline text with a custom Enter/Alt+Enter binding and prefilled defaults, which questionary wraps without exposing. Ollama runs on the host, not in Compose — Compose carries Postgres only.

---

## 11. CI

> **Built.** `.github/workflows/ci.yml` runs all five jobs on push to `main`, on every PR, and on `workflow_dispatch` (the "Run workflow" button). It landed late — this was M0 scope — and its first act was to catch what had accumulated meanwhile: 13 `mypy --strict` errors in `cli/prompts.py` and two files failing `ruff format --check`, all left by the prompt-toolkit migration. Fixed; every gate is green.

Five required checks on every PR. Four are fast and DB-free; only `integration` pays for a container.

| Job | Runs | Gate |
|---|---|---|
| `lint` | `ruff check`, `ruff format --check` | style and obvious bugs |
| `types` | `mypy --strict` on `src` and `tests` | type errors |
| `architecture` | `lint-imports` | Clean Architecture layer contract |
| `unit` | `pytest -m "not integration"` | domain + application, no Postgres |
| `integration` | `pytest -m integration` against `pgvector/pgvector:pg17` | repositories, migrations, CLI |

Workflow file: `.github/workflows/ci.yml`. Contract file: `.importlinter`.

Three decisions in there worth keeping:

- **Split unit from integration by pytest marker.** Most failures are logic errors and surface in under a minute; only the last job waits on a database. This is only possible because the layering keeps the domain and use cases DB-free — the architecture pays for itself in CI time.
- **`alembic check` in the integration job.** Catches SQLAlchemy models edited without a matching migration, which is the most common silent break in this stack and never shows up in tests until something else fails oddly.
- **Postgres as a service container, not testcontainers.** Faster in CI, since the runner pulls one image and reuses it across the job. Testcontainers stays for local runs; the `database_url` fixture uses `SEMANTIC_DB_DATABASE_URL` when it is set and starts a container when it is not, so the tests themselves never branch.
- **Ollama installed on the runner, with the model cached.** `record add` embeds on save, so the end-to-end tests need a real embedder — stubbing it there would test the stub. `~/.ollama/models` is an `actions/cache` entry keyed on the model name, which keeps the ~1.2GB `bge-m3` pull to the first run. The Ollama-backed tests still skip themselves when nothing answers on the configured URL, so a checkout without Ollama runs the rest of the suite instead of failing.

`import-linter` enforces four contracts: the inward-only layer order, no framework imports in `domain`, no framework imports in `application`, and no CLI reaching past use cases into repositories. Without this in CI, the layering is a diagram in a README rather than a property of the code.

Set all five as required status checks in branch protection, otherwise a red PR is still mergeable.

---

## 12. Milestones

| # | Deliverable | Done when | Status |
|---|---|---|---|
| M0 | Compose (Postgres + pgvector, Ollama), Alembic, settings, Typer skeleton, layer structure, `import-linter`, **CI workflow** | `semantic-db --help` works; all five CI jobs green on the first PR | **done** — the workflow landed after M5 rather than first; Ollama runs on the host, not in Compose |
| M1 | Schema model, validation, `collection create` (flags), persistence | `collection create products --field ...` writes a collection | **done** |
| M2 | Interactive wizard over the same use case, with render preview | `collection create products` with no flags works end to end | **done** |
| M3 | `OllamaEmbeddingProvider`, renderer, `record add` (flags), embed on save | A record is stored with its vector | **done** |
| M4 | Interactive `record add` with schema-driven prompts and the add-another loop | 30+ records entered by hand without pain | **done** |
| M5 | `search` with cosine top-k, Rich output, `--explain` | Query returns relevant records | **done** |
| M6 | `collection list/show`, `record list/show` via `queries.py` | Corpus inspectable without `psql` | open — `Queries` exists with `get_collection` only |
| M7 | `collection delete` (cascade + typed confirm), `record delete` | Destructive paths covered by integration tests | open |
| M8 | `record edit` (re-render + re-embed atomically) | Payload, rendered text, and vector never diverge | open |
| M9 | `collection edit` — additive and `embed`-toggle only, with full re-embed | Rejected changes fail with a clear reason | open |

**Second-collection test before M5:** create a collection with a completely different shape (books: `author`, `published`, `genres`) and add a few records. If anything breaks, the schema abstraction is wrong, and it's much cheaper to find out here. **Done** — `books` lives in `tests/schemas.py` alongside `products` and runs through the rendering, validation, and CLI tests. It exercised `date`, `bool`, and `array<string>`; the schema abstraction held.

Current test surface: 93 unit tests, 3 skipped (domain, use cases against fakes, CLI flag paths) and 16 integration tests (repositories, Ollama, CLI end to end).

### 12.1 Deviations from this spec, as built

| Change | Where | Why |
|---|---|---|
| `string` type dropped; `text` is the only text type | §4.1 | Two types with one behaviour between them. `text` covers both, and one prompt path means one place for the multiline handling. |
| `$EDITOR` dropped for `text` input | §5.1 | Text entry is terminal-only: Enter submits, Alt+Enter inserts a newline. Shelling out to an editor mid-wizard broke the add-another rhythm, and an unset or missing `$EDITOR` failed in a way that was hard to explain. |
| `enum` is completion, not a select list | §5.1 | prompt-toolkit's completer over the declared values, with `(skip)` prepended when the field is optional. Typing is faster than arrowing once the value list is known. |
| `questionary` → `prompt-toolkit` | §10 | The wizard needs custom key bindings and prefilled defaults; questionary hides both. |
| Ollama out of Compose | §12 M0 | It runs on the host with the model already pulled; a second copy in a container duplicates a multi-GB model download. |
| `search` shows distance, no separate score column | §6 | One ranking number, the one the index uses. |
| `RecordRepository.embedding_models` added | §9.1 | `search` must reject a corpus embedded with a different model rather than return meaningless distances. |
| CI workflow landed after M5, not in M0 | §11 | Slipped, then caught 15 accumulated lint and type failures the moment it ran. R6's point, demonstrated. |
| `record add` requires a TTY for the interactive path | §5.1 | Without a TTY it fails naming `--set`, instead of hanging on a prompt nothing will answer. |

---

## 13. Roadmap (post-MVP)

Ordered by what each one buys, not by effort.

| Step | Why |
|---|---|
| **Eval harness** — golden set, recall@k / MRR / nDCG, `eval compare` | The single thing that turns this from a demo into a portfolio project. Every change after this is measurable instead of vibes. |
| Typed filters — `filter` flag, filter compiler, per-field expression indexes | The actual point of structured records; combines with semantic search in a way pure-vector demos can't |
| Lexical search + RRF fusion | Usually the largest quality jump; needs the eval harness to prove it |
| Bulk ingest (JSONL/CSV) + export | Needed once the corpus outgrows hand entry, which the eval harness will force |
| Full schema migration — remove field, change type, required field | v1 rejects these; needs a coercion strategy per type pair |
| Second embedding model + comparison | Requires `model` in the embeddings PK |
| NL → typed filters (LlamaIndex auto-retrieval) | The schema is already machine-readable, so the filter spec is generated, not hand-written |
| Reranking | Local LLM only, no cross-encoder in Ollama; measure before keeping |

---

## 14. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Schema abstraction only works for the demo domain | **Closed** — `books` passed the second-collection test (§12) |
| R2 | Hand entry too tedious to reach a useful corpus | Add-another loop, prefilled defaults, flag path for scripted seeding; bulk ingest is first on the roadmap if it bites. `scripts/seed_products.sh` exists but **is written against a `--field name type --embed` syntax that was never built** — it needs rewriting to the `--field "name:type:flags"` grammar of §4.2 before it runs |
| R3 | Embedding on save feels slow | **Measured** (§16): the `embed` span is p50 384ms / p95 569ms on `bge-m3` for a single card, against 20ms for the pgvector query. Tolerable, and the guess it replaces was right. If it stops being tolerable, queue and embed on a background pass |
| R4 | Clean Architecture becomes ceremony at this size | One use case per command; no port without a second implementation or a test that needs the seam |
| R5a | `collection edit` re-embeds the whole corpus on an `embed` toggle | Progress bar, cost stated before starting, `--yes` for scripts; corpus is small by design |
| R5b | Accidental `collection delete` | Typed-name confirmation, not y/n; `--yes` only for scripted use |
| R5 | Scope creep back toward v0.6 | §3 and §13 are binding; nothing from the roadmap enters v1 |
| R6 | CI green but layering already broken by the time contracts are added | `import-linter` landed in M0 with four contracts and never broke. The workflow itself slipped to after M5, and the drift it let through was in lint and types rather than layering — the contracts held because they were written first. |

---

## 15. Open questions

1. ~~**Demo domain** — which collection ships as the example?~~ **Answered: industrial `products`** (pumps, motors, valves, sensors), used in the README, the seed script, and the tests, with `books` as the second shape.
2. ~~**Record language** — Polish, English, or mixed?~~ **Answered: English**, throughout the fixtures and the seed corpus. `bge-m3` still allows a Polish corpus later without a schema change.
3. **Branch protection** — the workflow exists; the five jobs still have to be set as required status checks in the repository settings, or a red PR stays mergeable (§11).

---

## 16. Observability

Off by default (`SEMANTIC_DB_TELEMETRY_ENABLED=false`). Switched on, the CLI exports
OpenTelemetry traces, metrics and logs over OTLP/HTTP to `grafana/otel-lgtm` running
locally — one container beside Postgres, reached with `make obs-up`. Nothing leaves the
machine, so §1's "fully local" claim is unchanged.

One command is one trace:

```
cli.command → use_case.* → { embed → POST /api/embed, db.search → SELECT }
```

The hand-written spans carry the domain facts — collection, k, query, hit count, distance
min and mean, embedding model and dimension. The HTTP and SQL children come from the
httpx and SQLAlchemy instrumentations.

| # | Decision | Consequence |
|---|---|---|
| D1 | OTel and Grafana only; no `searches` table | This buys latency insight, not retrieval quality. Eval data needs durable rows and belongs to the eval harness (§13), not to 14-day trace retention |
| D2 | OTel packages are core dependencies | Every install carries them; no conditional import and no `ImportError` branch to test |
| D3 | Query text recorded verbatim in `semantic_db.query` | Acceptable while the exporter is local-only and the corpus is the user's own. Revisit before any remote exporter |
| D4 | CI runs `otel-lgtm` as a service container | The integration test asserts a trace really lands, not just that spans have the right shape |
| D5 | Off unless explicitly enabled | A default install builds no providers, starts no threads and never warns about an absent collector |
| D6 | All three signals | Logs are the weakest leg: the OTel Python logs SDK is still private, so every `_logs` import sits in one file |
| D7 | Metrics derive from spans | `Telemetry.span()` records `semantic_db_span_duration_milliseconds` and, on failure, `semantic_db_errors_total`. One port method, so the metrics cannot drift from what is traced |

`Telemetry` is the fourth port and earns its place under §9.1 twice over: `NullTelemetry`
ships as the default implementation and `RecordingTelemetry` is the seam the use-case tests
assert through. The port is framework-free, and the import contracts now forbid
`opentelemetry` in both `domain` and `application`.

Instrumentation is observation only: it never changes an exit code, a Rich message or a
failure path. A collector that is down costs the CLI a couple of seconds at teardown — one bounded
export attempt per signal — and prints nothing.
