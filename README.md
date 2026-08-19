# semantic-db

Local CLI for **semantic search over user-defined structured records**. Define a schema, add
records against it, search them in natural language. Postgres + pgvector for storage, Ollama for
embeddings. No API keys, no cloud.

Current state: **M0–M3** of [`specs/mvp-foundation-m0-m3.md`](specs/mvp-foundation-m0-m3.md) —
schema definition, collection creation (flags and wizard), rendering, embedding, and
`record add`. Search (M5) and the management commands (M6–M9) are not built yet.

## Prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Docker (Postgres 17 + pgvector; also used by the integration tests)
- [Ollama](https://ollama.com) running on the host, with the embedding model pulled:

```bash
ollama pull bge-m3      # 1024-dimensional, multilingual
```

`bge-m3` is not optional: the `embeddings.vec` column is `halfvec(1024)`, and a different model
means a different dimension. Adding a record fails with a message naming the mismatch.

## Quickstart

```bash
uv sync
make up          # Postgres on localhost:5432
make migrate     # alembic upgrade head

uv run semantic-db collection create products \
    --field "title:string:embed,required" \
    --field "description:text:embed" \
    --field "category:enum(pumps|motors|valves|sensors):embed" \
    --field "year:int:embed" \
    --field "price:float:embed:unit=PLN"

uv run semantic-db record add products \
    --set "title=Hydraulic pump HP-400" \
    --set "category=pumps" \
    --set "year=2019" \
    --set "price=4200" \
    --set "description=Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB."
```

Run `semantic-db collection create products` with no `--field` for the interactive wizard. Both
paths build the same schema and go through the same use case.

### Field spec grammar

```
name:type[:flags][:key=value]
```

Types: `string`, `text`, `enum(a|b|c)`, `int`, `float`, `bool`, `date`, `array<string>`.
Flags: `embed`, `required` (comma-separated or as separate segments).
Options: `unit=…` (int and float only, used when rendering).

## How a record becomes searchable

Each record renders into **one labelled card** — no chunking — and that exact string is what gets
embedded and stored:

```
Title: Hydraulic pump HP-400
Description: Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.
Category: pumps
Year: 2019
Price: 4200 PLN
```

Fields render in declaration order; `embed: false` fields and absent optional values are omitted.
Embedding happens on save, so **added means searchable** — a record with no vector is never a
reachable state.

## Configuration

Every setting has a default; override via `.env` or the environment (see `.env.example`):

| Variable | Default |
|---|---|
| `SEMANTIC_DB_DATABASE_URL` | `postgresql+asyncpg://semantic:semantic@localhost:5432/semantic_db` |
| `SEMANTIC_DB_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `SEMANTIC_DB_EMBEDDING_MODEL` | `bge-m3` |
| `SEMANTIC_DB_EMBEDDING_DIM` | `1024` |

## Development

```bash
make check              # ruff, ruff format --check, mypy --strict, lint-imports, unit tests
make test-integration   # testcontainers Postgres + real Ollama, then alembic check
```

CI is deferred: there is no `.github/workflows/ci.yml` yet, but the `.importlinter` contracts and
all five gates run locally through `make check`, so the layering is enforced by a command rather
than by a diagram. Adding the workflow later is a transcription of the Makefile targets.

## Design notes worth knowing

**Payloads are JSONB.** A table per collection with real typed columns would be faster, but it
requires generating and migrating DDL per user schema, and Alembic plus user-defined DDL do not
coexist peacefully. JSONB is what vector databases do for metadata and it survives arbitrary
schemas. `infrastructure/mappers.py` is the only place that knows JSONB has no date type.

**`rendered` is stored, not recomputed.** It is the exact string that produced the vector.
Recomputing it after a template change would silently drift from what the index contains.

**CQRS-lite layering.** Write operations carry rules — validation, rendering, re-embedding — and
stay as use cases. Read operations apply no rules and will go through a single `queries.py` façade
from M6, rather than eight five-line pass-through classes.

**Three ports, no fourth.** `EmbeddingProvider`, `CollectionRepository`, `RecordRepository`. A port
earns its place with a second implementation or a test that needs the seam; a `Renderer` interface
would not, because rendering is a pure function. Methods are added as their milestone lands, so
nothing in `ports.py` is a stub.

## Layout

```
src/semantic_db/
├── domain/           # entities, rendering, validation — no frameworks
├── application/      # ports + use cases — no frameworks
├── infrastructure/   # SQLAlchemy, Alembic, Ollama
├── cli/              # Typer commands, questionary wizard
└── container.py      # composition root — the only place that wires
```

Dependencies point inward only, enforced by four `import-linter` contracts.
