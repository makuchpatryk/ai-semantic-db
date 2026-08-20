# semantic-db M4–M5 — Interactive `record add` + `search` — Implementation Plan

**Source PRD:** `PRD.md` v1.0 · **Covers:** milestones M4, M5 · **Builds on:** `specs/mvp-foundation-m0-m3.md` (shipped, `c39d873`) · **Status:** awaiting approval

## Summary

Close the loop from empty database to useful retrieval. M4 makes `record add` interactive — schema-driven prompts, per-field re-prompt on bad input, sticky defaults, and the add-another loop — so a corpus can be entered without `--set`. M5 adds `search`: embed the query, cosine top-k over pgvector, Rich table, `--explain`. After M5 the three core commands of PRD §2 all work end to end.

M5 is the first read path in the project, so it also introduces `application/queries.py` (schema lookup, needed by M4's prompts) and the first `RecordRepository` read methods. Both are deliberately kept to what these two milestones consume.

## Success Criteria

1. `semantic-db record add products` with no flags prompts every declared field in declaration order, previews the rendered card, saves on `Y`, and offers `Add another?`.
2. Entering `abc` at an `int` prompt prints the error and re-asks **that field only**; the rest of the half-entered record survives.
3. The second record in the loop shows the first record's values as prefilled defaults; pressing Enter through them stores an identical payload.
4. Interactive entry and `--set` produce a byte-identical `records.payload` for the same values — verified by a unit test asserting both paths against the same expected payload.
5. `semantic-db search products "quiet pump for industrial use"` returns a Rich table of rank, cosine distance, and the first embeddable field, ordered by ascending distance.
6. `--k 3` returns at most 3 rows; `--explain` additionally prints each hit's full `rendered` text.
7. Searching a collection whose embeddings were written by a different model than `SEMANTIC_DB_EMBEDDING_MODEL` exits 2 naming both models; **no embedding call is made**.
8. `./scripts/seed_products.sh` creates `products` and adds 20 records; the query in criterion 5 puts a quiet/low-noise pump first.
9. `make check` green (ruff, ruff format, mypy --strict, 4 import contracts, unit tests) and `pytest -m integration` green.

## Scope & Constraints

**In scope:**
- M4 — `cli/prompts.py` record prompts, per-type input handling (PRD §5.1 table), re-prompt on invalid, sticky defaults, preview + `Save?`, `Add another?` loop.
- M5 — `SearchRecords` use case, `RecordRepository.search`, cosine top-k SQL, `search` CLI command with `--k`/`--explain`, embedding-model guard.
- `application/queries.py` with **one** method (`get_collection`) — M4's prompts need the schema and the CLI may not touch repositories.
- `scripts/seed_products.sh` — 20 English products records via the public CLI.

**Out of scope:** `collection list/show`, `record list/show` (M6 — `queries.py` grows there, not here), `delete` (M7), `record edit` (M8), `collection edit` (M9), everything in PRD §3/§13. No filters, no hybrid, no reranking, no `--json` output.

**Decisions taken in grilling:**

| # | Decision | Consequence |
|---|---|---|
| D1 | **Sticky defaults on every field**, not just enums | Fastest bulk entry (PRD R2). Backstop against a copied value: the preview + `Save?` on every record, and `*` marks required fields. |
| D2 | **`typer.edit()` for `text`, multiline prompt as fallback** | Fallback triggers when `$EDITOR`/`$VISUAL` are unset, stdin is not a TTY, or the editor call raises. Never dead-ends. |
| D3 | **`--set` stays fully non-interactive** | Any `--set` means the flag path; a missing required field exits 2 rather than opening a prompt. Scripts can never hang. Today's behaviour, unchanged. |
| D4 | **Search refuses on model mismatch** | Cross-model cosine scores are meaningless; silent garbage is worse than a blocked command. Checked before embedding, so a mismatch costs no Ollama call. |
| D5 | **Invalid prompt input re-prompts that field** | Mirrors the `collection create` wizard, which re-prompts one bad field instead of discarding the schema. |
| D6 | **Raw cosine distance is the only score shown** | Lower = better, in the table and in `--explain`. **Deviates from PRD §6**, which words it as "score … `--explain` adding the raw cosine distance" — PRD §6 gets updated in step 13. |
| D7 | **`scripts/seed_products.sh` ships in the repo** | Repeatable corpus for eyeballing retrieval; doubles as the R2 mitigation. Shell + public CLI only — no import path, no second way to write records. |

**Assumptions (not blocking, stated for the record):** `--k` defaults to **10** (PRD only shows `--k 5` as an example); seed corpus is **English**, domain `products`, per the M0–M3 spec.

**Hard constraints:** unchanged from M0–M3 — Python 3.12, SQLAlchemy 2.0 async, Pydantic v2, `mypy --strict` on `src` *and* `tests`, `domain`/`application` import no frameworks, `cli` never imports `infrastructure`, `halfvec(1024)` fixed to `bge-m3`.

---

## Architecture & Design

### High-Level Flow — M4

```
record add products                    (no --set)
        │
   cli/commands/record.py
        │  run(queries.get_collection) ──────────► SqlCollectionRepository
        │        └─ Collection.schema                      [one round trip, once]
        ▼
   loop:
     prompt_record_values(schema, defaults)        [cli/prompts.py]
        │   per field:  ask → blank? → coerce_value(field, raw)
        │                        ▲            │
        │                        └── PayloadError: print, re-ask same field
        ▼
     print_record_preview(schema, values)          [pure render(), domain]
        │
     confirm("Save?", default=True)
        ▼
     run(add_record.execute(cmd))  ──► AddRecord (unchanged: coerce → render → embed → store)
        │
     defaults = saved record.payload               [D1 sticky]
        ▼
     confirm("Add another?", default=True)
```

Coercion runs twice — once at the prompt (to re-ask immediately) and once inside `AddRecord`. That is intentional and safe: `coerce_payload` already accepts already-typed values, so the use case stays the single validation authority and the prompt layer is only an early, friendlier copy of it.

### High-Level Flow — M5

```
search products "quiet pump" --k 5 --explain
        │
   cli/commands/search.py
        │  asyncio.run(...)
        ▼
   SearchRecords.execute(cmd)                        [application]
        ├─ collections.get(name) ──────────► not found → CollectionNotFoundError (exit 2)
        ├─ records.embedding_models(cid) ──► {"bge-m3"} vs settings model
        │        └─ mismatch → EmbeddingModelMismatchError    [D4: before any embed call]
        ├─ embed_one(embedder, query) ─────► OllamaEmbeddingProvider  (dim + count checked)
        └─ records.search(cid, vec, k) ────► SqlRecordRepository
                                                 │
        ┌────────────────────────────────────────┘
        │  SELECT r.id, r.payload, r.rendered, e.vec <=> :q AS distance
        │  FROM embeddings e JOIN records r ON r.id = e.record_id
        │  WHERE r.collection_id = :cid
        │  ORDER BY e.vec <=> :q     ← must match halfvec_cosine_ops to use embeddings_hnsw
        │  LIMIT :k
        ▼
   SearchResult(schema, hits: list[ScoredRecord])
        ▼
   Rich table: #  distance  <first embeddable field>
   --explain:  one panel per hit with id + full rendered text
```

### Key Changes

**`src/semantic_db/domain/validation.py`** — extract the per-field branch of `coerce_payload` into a public `coerce_value(field: FieldDefinition, value: object) -> PayloadValue` (today's private `_coerce`). `coerce_payload` calls it, behaviour unchanged. The prompt loop needs to coerce one field at a time to re-ask it; without this the CLI would either duplicate the type table or reach into a private.

**`src/semantic_db/domain/record.py`** — `ScoredRecord.score: float` → `ScoredRecord.distance: float` (D6). The field has no readers yet, so this is a rename, not a migration.

**`src/semantic_db/domain/errors.py`** — add:
```python
class EmbeddingModelMismatchError(SemanticDbError):
    def __init__(self, collection: str, stored: str, current: str) -> None:
        super().__init__(
            f"collection '{collection}' was embedded with {stored}, "
            f"current model is {current}; re-embed the collection or switch the model back"
        )
```

**`src/semantic_db/application/ports.py`** — `RecordRepository` gains exactly two methods:
```python
async def search(self, collection_id: int, vec: list[float], k: int) -> list[ScoredRecord]: ...
async def embedding_models(self, collection_id: int) -> frozenset[str]: ...
```
`embedding_models` is a separate call rather than a flag on `search` so the guard can run **before** the query is embedded (D4). No fourth port — the guard needs data, not a seam.

**`src/semantic_db/application/embedding.py`** (new, ~15 lines) — `async def embed_one(embedder: EmbeddingProvider, text: str) -> list[float]`, lifted verbatim from `AddRecord._embed` (count check + dim check + `EmbeddingUnavailableError` messages). `AddRecord` and `SearchRecords` both call it; the "wrong model is pulled" message stays written once.

**`src/semantic_db/application/queries.py`** (new) — the read façade of PRD §7.5, opened with one method:
```python
class Queries:
    def __init__(self, collections: CollectionRepository) -> None: ...
    async def get_collection(self, name: str) -> Collection:  # raises CollectionNotFoundError
```
M6 adds `list_collections`, `show_collection`, `list_records`, `show_record` here. Arriving one milestone early is deliberate: M4's prompts are generated from the schema, and the CLI cannot reach a repository.

**`src/semantic_db/application/use_cases/search_records.py`** (new):
```python
@dataclass(frozen=True)
class SearchRecordsCommand:
    collection_name: str
    query: str
    k: int

@dataclass(frozen=True)
class SearchResult:
    schema: CollectionSchema      # so the CLI can label the table without a second round trip
    hits: list[ScoredRecord]
```

**`src/semantic_db/infrastructure/repositories.py`** — `SqlRecordRepository.search` and `.embedding_models`. `search` uses pgvector's `EmbeddingModel.vec.cosine_distance(vec)` in both the projection and the `ORDER BY`, joined to `RecordModel`, filtered on `collection_id`, `LIMIT k`. The schema for mapping comes from the joined `CollectionModel`, as `add` already does.

**`src/semantic_db/cli/prompts.py`** — `prompt_record_values(schema, defaults) -> dict[str, PayloadValue]`, plus one private asker per type:

| Type | Widget | Default from previous record |
|---|---|---|
| `string` | `questionary.text` | `default=str(prev)` |
| `text` | `typer.edit(prev)`, fallback `questionary.text(multiline=True)` | seeded into the buffer |
| `enum` | `questionary.select(choices)` | `default=prev` when still a declared value |
| `int` / `float` | `questionary.text`, coerced | `default=str(prev)` |
| `bool` | required → `confirm`; optional → `select(yes/no/(skip))` | `default` = previous answer |
| `date` | `questionary.text`, ISO coerced | `default=prev.isoformat()` |
| `array<string>` | `questionary.text`, comma-split | `default=", ".join(prev)` |

Optional `enum` gets a leading `(skip)` choice, and optional `bool` uses a select rather than a confirm, because `confirm` has no third state and "absent optional" must stay distinguishable from "explicitly false" — `render` skips exactly the fields `coerce_payload` omitted.

Prompt label: `f"{field.label}{' *' if field.required else ''}"`, with the unit appended for `int`/`float` (`price (PLN)`), matching PRD §5.1.

**`src/semantic_db/cli/commands/record.py`** — replace the "arrives in M4" error with the loop. Saving stays one `run()` per record.

**`src/semantic_db/cli/commands/search.py`** (new) + registration in `main.py` as a **top-level** command (`semantic-db search <collection> "<query>"`), not a sub-typer. `--k` is `typer.Option(10, min=1)`; `--explain` is a flag.

**`src/semantic_db/container.py`** — wire `queries` and `search_records`.

**`scripts/seed_products.sh`** — `set -euo pipefail`; `collection create` tolerated if it already exists (`|| echo "collection exists, adding records"`); then 20 `record add --set` calls covering all four enum values, with three deliberately low-noise/quiet pumps so criterion 8 has an unambiguous answer.

**No new dependencies. No migration** — `search` reads tables and the HNSW index that `0001_initial` already created.

### Alternative Approaches Considered

**Where the interactive loop holds its connection**
- *(chosen)* **One `run()` per record.** Prompts stay fully synchronous and outside the event loop; a new engine per record costs a connection (~20ms) against a ~400ms embed. Trivially testable.
- One container for the whole loop, prompting between `await`s. Saves the reconnect, but blocks the event loop inside `asyncio.run` and makes the command hard to test. The saving is noise next to the embed call.
- Batch: collect N records, then embed and write them all. Breaks "added means searchable" feedback per record (PRD §5.1) and buys nothing at this corpus size.

**How the model guard gets its data**
- *(chosen)* **`RecordRepository.embedding_models(collection_id)`.** One `SELECT DISTINCT`, runs before embedding, empty set on an empty collection so a fresh collection is never blocked.
- A `model` argument on `search` that filters the `WHERE`. Cheaper by one query, but a mismatch then returns *zero rows* instead of an error — exactly the silent-garbage failure D4 exists to prevent.
- Store the model on `collections`. Correct long-term, but it is a migration and it pre-empts the roadmap's multi-model step; `embeddings.model` already holds the truth.

**Score presentation** — D6 above. Similarity (`1 - distance`) reads more naturally, but it is a derived number that would then disagree with what `--explain` and any future eval harness print. One number, the one Postgres returned.

**Sticky defaults** — D1 above. Blank-every-time is simpler and cannot leak a stale value, but PRD R2 names hand-entry tedium as the risk most likely to kill the corpus, and the per-record preview already gates every save.

---

## Implementation Steps

1. **`coerce_value` extraction** — make `_coerce` public in `domain/validation.py`, `coerce_payload` delegates. Add unit tests for the new public entry point. No behaviour change.
2. **`ScoredRecord.score` → `.distance`** in `domain/record.py`; add `EmbeddingModelMismatchError` to `domain/errors.py`.
3. **`application/embedding.py`** — extract `embed_one` from `AddRecord._embed`; `AddRecord` calls it. Existing use-case tests must stay green untouched.
4. **`application/queries.py`** — `Queries.get_collection`; wire into `Container`.
5. **M4 prompts** — `prompt_record_values` in `cli/prompts.py` with the per-type askers, the re-prompt loop (D5), blank/required handling, and sticky `defaults` (D1). Unit tests with the existing `FakeQuestionary`, extended for `multiline` and the editor fallback.
6. **`text` field editor** — `typer.edit()` with the `$EDITOR`/`$VISUAL` + `isatty` gate and multiline fallback (D2), monkeypatched in tests.
7. **M4 command** — rewrite `record add`'s interactive branch: fetch schema once, prompt → preview → `Save?` → `run(add_record)` → sticky defaults → `Add another?`. `--set` path untouched (D3).
8. **Ports + fakes** — add `search` / `embedding_models` to `RecordRepository` protocol and to `InMemoryRecordRepository` (cosine over the stored fake vectors, sorted ascending).
9. **`SearchRecords` use case** + `SearchResult`; unit tests against the fakes: ordering, `k` limit, unknown collection, model mismatch raises **without** calling the embedder (assert `FakeEmbeddingProvider.calls == []`), empty collection returns no hits.
10. **`SqlRecordRepository.search` + `.embedding_models`**; integration tests in `tests/integration/test_repositories.py` — distances ascending, `k` honoured, `collection_id` isolation between two collections.
11. **`search` CLI** — `cli/commands/search.py`, table + `--explain` panels, empty-result and empty-collection messages; register in `main.py`; wire `search_records` into the container.
12. **`scripts/seed_products.sh`** — 20 records, `chmod +x`, referenced from the README.
13. **Docs** — README command list gains `search` and interactive `record add`; **PRD §6 reworded to distance-only (D6)**; PRD §12 M4/M5 rows ticked.
14. **Full gate** — `make check`, `pytest -m integration`, `alembic check` (expected: no pending changes, since no model changed), then run criterion 8 by hand against the seeded corpus.

### Risks & Mitigations

- **R-A: the `halfvec` query parameter is sent as `vector`, so the `ORDER BY` misses the `halfvec_cosine_ops` index or errors on type.**
  - Integration test in step 10 is the tripwire — it fails loudly, not silently.
  - Fallback: `cast(literal(vec), HALFVEC(EMBEDDING_DIM))` in both the projection and the `ORDER BY`, so the two expressions stay identical (they must, or the index is skipped).
- **R-B: HNSW is not used at all at 20 records** — the planner prefers a seq scan on tiny tables.
  - Correctness is unaffected; do not assert on the plan in tests (planner-dependent, flaky). Verify once by hand with `EXPLAIN` on a seeded corpus and move on.
- **R-C: a sticky default is saved unnoticed** (D1's cost).
  - Preview + `Save?` on every record; `*` on required fields; the value is visible in the prompt before Enter.
- **R-D: `typer.edit()` hangs or explodes in a non-TTY** (CI, `CliRunner`, piped stdin).
  - Gate on `$EDITOR`/`$VISUAL` **and** `sys.stdin.isatty()`, wrap the call, fall back to the multiline prompt (D2). Covered by a unit test with both env vars cleared.
- **R-E: the loop reconnects per record and feels sluggish at 30+ records.**
  - Measure during step 14. If it bites, one container for the whole loop is a contained change behind `run()` — the flow above is the only caller.
- **R-F: `queries.py` arriving in M4 becomes a dumping ground.**
  - It ships with exactly one method and a comment naming M6 as the milestone that fills it.
- **R-G: retrieval quality is disappointing at criterion 8** — the real risk of M5, and the one the milestone exists to expose.
  - The corpus and the query are both in the repo, so it is reproducible. Levers in order: the rendered card (labels, field order, which fields are `embed`), then the model. Anything beyond that is the eval harness, which is roadmap, not this plan.

## Test Strategy

**Unit — no Postgres, no Ollama**
- `domain`: `coerce_value` per type, including the error path for each (extends `tests/unit/test_validation.py`).
- `cli/prompts.py` (`tests/unit/test_record_prompts.py`, new): interactive values == `--set` values for the same record (criterion 4); re-prompt on a bad `int` keeps earlier fields (criterion 2); blank optional omitted vs blank required re-asked; sticky defaults reach the widgets as `default=`; `(skip)` on an optional enum/bool omits the field; `PromptAborted` on Ctrl-C; editor fallback with `$EDITOR`/`$VISUAL` unset.
- `application` (`tests/unit/test_use_cases.py`): `SearchRecords` ordering, `k`, unknown collection, mismatch-without-embedding, empty collection.
- `cli` (`tests/unit/test_cli.py`): `search --help`; `--k 0` rejected by Typer; `record add --set title=X` on a required-field-short payload still exits 2 (D3 regression guard).

**Integration — testcontainers `pgvector/pgvector:pg17`**
- `test_repositories.py`: `search` returns ascending distances, honours `k`, never crosses collections; `embedding_models` returns `{"bge-m3"}` and `frozenset()` for an empty collection.
- `test_search.py` (new): seed ~8 products through the real stack, assert the quiet-pump query ranks the quiet pump first; assert the model-mismatch guard exits before embedding (settings override).
- `test_cli_end_to_end.py`: `search` prints a table containing the expected title; `--explain` contains the full rendered card; searching an unknown collection exits 2.

**Not automated, by design:** the interactive `record add` end to end. `questionary` needs a TTY that `CliRunner` does not provide, and PRD §9.2 already scopes CLI tests to the flag path. Prompt logic is covered by the fake-questionary unit tests; the wiring (schema fetch → loop → save) is verified by hand in step 14.

**Manual**
- `./scripts/seed_products.sh`, then criteria 5/6/8 by eye.
- One hand-entered record through the loop, including a deliberate bad `int` and an `$EDITOR` `text` field.
- `SEMANTIC_DB_EMBEDDING_MODEL=nomic-embed-text semantic-db search products "x"` → criterion 7's message.

## Success Checklist

- [ ] All 9 success criteria met, criteria 5/6/8 evidenced against the seeded corpus
- [ ] `make check` green (ruff · ruff format · mypy --strict · 4 import contracts · unit)
- [ ] `pytest -m integration` green, `alembic check` reports no pending model changes
- [ ] `search` and interactive `record add` documented in the README
- [ ] PRD §6 reworded to distance-only (D6); PRD §12 M4/M5 ticked
- [ ] No regression on the `--set` path or on `collection create` (both wizard and flags)
- [ ] `git status` clean of stray fixtures; `scripts/seed_products.sh` executable and committed

## Timeline & Estimates

| Phase | Work | Estimate |
|---|---|---|
| 1 | Steps 1–4 — extractions, `queries.py`, wiring | ~1.5 h |
| 2 | Steps 5–7 — M4 prompts, editor, loop | ~3.5 h |
| 3 | Steps 8–11 — M5 use case, SQL, CLI | ~3 h |
| 4 | Steps 12–14 — seed script, docs, full gate + manual pass | ~2 h |
| **Total** | | **~10 h** plus buffer for R-A and R-G |

## Open Questions

None blocking. Two assumptions carried into the build, flagged here rather than left implicit:

- [ ] `--k` default of **10** (PRD only ever shows `--k 5` as an example) — change is a one-line default if you want 5.
- [ ] If criterion 8 disappoints (R-G), the fix lands in the rendered card, not in this plan's architecture — and anything measurement-driven is the roadmap's eval harness, not M5.
