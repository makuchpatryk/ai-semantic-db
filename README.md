# semantic-db

> **Local semantic search for structured data.** Define any schema, add records, search in natural language. Fully local—no APIs, no cloud.

`semantic-db` is a CLI tool that brings semantic search to your own data. Define a collection with typed fields, add records, and query them using plain English. Built on Postgres + pgvector (local storage) and Ollama (local embeddings).

**Status:** MVP in progress. Milestones M0–M5 complete — define a collection, add records (flags or wizard), search them. Management commands (`list`, `show`, `edit`, `delete`) are M6–M9 and not built yet. [Roadmap →](PRD.md#12-milestones)

**Quick links:**  
[Getting Started](#getting-started) • [Why semantic-db?](#why-semantic-db) • [Configuration](#environment) • [Architecture](#architecture) • [Development](#development)

## Why semantic-db?

Existing semantic search tools are cloud-based or tightly coupled to a specific data source. `semantic-db` is:

- **Schema-driven:** You define the structure; the tool adapts to it
- **Fully local:** All data stays on your machine. No APIs, no rate limits, no vendor lock-in
- **Typed fields:** text, enums, ints, floats, bools, dates, string arrays—with units and rendering rules
- **Simple:** A CLI and a schema. That's it

**Use cases:**
- Search your own documents / articles / records by meaning, not keywords
- Build semantic indexes for product catalogs, knowledge bases, research notes
- Experiment with embeddings locally before deploying

---

## Prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Docker (Postgres 17 + pgvector; also used by the integration tests)
- [Ollama](https://ollama.com) running on the host, with the embedding model pulled:

```bash
ollama pull bge-m3      # 1024-dimensional, multilingual
```

`bge-m3` is not optional: the `embeddings.vec` column is `halfvec(1024)`, and a different model
means a different dimension. Adding a record fails with a message naming the mismatch.

## Getting Started

### 1. Set up

```bash
uv sync
make up          # Start Postgres on localhost:5432
make migrate     # Run database migrations
```

### 2. Create a collection

Define a schema with typed, embeddable fields:

```bash
uv run semantic-db collection create products \
    --field "title:text:embed,required" \
    --field "description:text:embed" \
    --field "category:enum(pumps|motors|valves|sensors):embed" \
    --field "year:int:embed" \
    --field "price:float:embed:unit=PLN"
```

Prefer interactive? Run with no `--field` flags for a guided wizard.

### 3. Add records

```bash
uv run semantic-db record add products \
    --set "title=Hydraulic pump HP-400" \
    --set "category=pumps" \
    --set "year=2019" \
    --set "price=4200" \
    --set "description=Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB."
```

Records are embedded and searchable immediately upon save. With no `--set` flags you get the schema-driven wizard, which keeps asking `Add another?` until you say no.

### 4. Search

```bash
uv run semantic-db search products "quiet pump for industrial use"
uv run semantic-db search products "quiet pump" --k 5 --explain
```

Results are a Rich table of rank, cosine distance, and the first embeddable field. `--explain` adds the full rendered text of every hit.

Search refuses to run if the collection was embedded with a model other than the configured one — cross-model distances look plausible and mean nothing.

## Field Spec

Schemas use a compact grammar:

```
name:type[:flags][:key=value]
```

**Types:** `text`, `enum(a|b|c)`, `int`, `float`, `bool`, `date`, `array<string>`  
**Flags:** `embed`, `required` (comma-separated or separate)  
**Options:** `unit=…` (int/float only; affects rendering)

Example: `price:float:embed:unit=PLN` → embeds, renders as "Price: 4200 PLN"

## How Records Are Indexed

Each record renders into one formatted card and embedded as-is:

```
Title: Hydraulic pump HP-400
Description: Cast-iron housing, rated 400 l/min, low-noise operation at 62 dB.
Category: pumps
Year: 2019
Price: 4200 PLN
```

Fields marked `embed: false` are excluded; optional fields omit missing values. Embedding happens on save—**added means searchable**, never a partial state.

## Environment

Configure via `.env` or environment variables (see `.env.example`):

| Variable | Default |
|---|---|
| `SEMANTIC_DB_DATABASE_URL` | `postgresql+asyncpg://semantic:semantic@localhost:5432/semantic_db` |
| `SEMANTIC_DB_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `SEMANTIC_DB_EMBEDDING_MODEL` | `bge-m3` |
| `SEMANTIC_DB_EMBEDDING_DIM` | `1024` |

## Development

```bash
make check              # type check, format, lint, unit tests
make test-integration   # integration tests (real Postgres + Ollama)
```

The same five gates run in CI (`.github/workflows/ci.yml`) on every push to `main`, every PR, and on demand from the Actions tab: `lint`, `types`, `architecture`, `unit`, and `integration`. Only `integration` needs services — Postgres as a job service container, Ollama installed on the runner with `bge-m3` cached.

Locally, integration tests start their own Postgres via testcontainers unless `SEMANTIC_DB_DATABASE_URL` already points at one. Tests that need a live Ollama skip themselves when none is running.

## Architecture

### Key Design Decisions

**JSONB payloads, not per-collection DDL.** Avoids complex migration logic and supports arbitrary schemas. Trade-off: slower than native columns, but simpler.

**Rendered text is stored.** The exact string that produced the vector is persisted. Prevents silent drift if a template changes after embeddings are created.

**CQRS-lite.** Write operations (add, update, delete) carry business rules and live as use cases. Reads are rule-free and route through a single `queries.py` façade — currently just `get_collection`; the rest arrives with M6.

**Minimal ports.** Three boundaries: `EmbeddingProvider`, `CollectionRepository`, `RecordRepository`. Each earns its place with a second implementation or a test seam.

### Project Structure

```
src/semantic_db/
├── domain/           # Entities, rendering, validation
├── application/      # Ports, use cases
├── infrastructure/   # SQLAlchemy, Alembic, Ollama clients
├── cli/              # Typer CLI, prompts, wizards
└── container.py      # Composition root
```

Dependencies flow inward. Enforced by `import-linter` contracts.

## Roadmap

| Milestone | Status | Scope |
|-----------|--------|-------|
| **M0–M3** | ✅ Complete | Schema definition, collection creation, embedding, `record add` (flags) |
| **M4** | ✅ Complete | Interactive `record add` — schema-driven prompts, add-another loop |
| **M5** | ✅ Complete | Semantic search: cosine top-k, Rich table, `--explain` |
| **M6** | 📋 Planned | `collection list/show`, `record list/show` |
| **M7–M9** | 📋 Planned | Deletes, `record edit` (re-embed), additive `collection edit` |

Full specs: [`specs/`](specs/) · milestone table: [PRD §12](PRD.md#12-milestones)

---

## Learn More

- **[Specs](specs/)** — Detailed design docs for each milestone
- **[PRD](PRD.md)** — Product requirements and vision
- **[Architecture](README.md#architecture)** — Design decisions and trade-offs

## Contributing

Contributions welcome. Current focus: M6 (read commands). See [`specs/`](specs/) for planned work.

Start with:
```bash
make check              # Run all checks locally
make test-integration   # Integration tests
```
