# M9: `collection edit` — Implementation Plan

## Summary

M9 is the last hole in collection management (create/list/show/delete already ship) and
the one PRD calls out as "the one genuinely hard command" (§7.3), because it is a schema
migration wearing a CLI command. v1 restricts it to four changes — rename, add an
optional field, toggle `embed` on a field, add enum values — and rejects everything else
(remove a field, add a required field, change a type, remove an enum value) by naming the
reason and pointing at `delete` + recreate.

## Success Criteria

- `collection edit <name> [--rename NEW] [--add-field SPEC]... [--embed FIELD]...
  [--no-embed FIELD]... [--enum-add FIELD=VALUE]... [--yes]` applies any combination of
  the four allowed changes in one call, atomically per PRD §7.2's bar ("payload/rendered/
  vector never diverge") extended to a whole collection.
- Adding a required field via `--add-field` is rejected before anything is touched, naming
  the field and pointing at `delete` + recreate — same for the three changes with no flag
  surface at all (remove field, change type, remove enum value: simply inexpressible).
- Rename and enum-add are metadata-only: no record is read or re-embedded.
- Add-field and embed-toggle trigger a full-corpus re-render + re-embed, with a progress
  bar, gated behind a y/N confirmation stating the record count (bypassable with `--yes`).
- If the Ollama call for any batch fails, the collection's schema and every record's
  `rendered`/vector are left exactly as they were — no partial migration.
- Covered by unit tests (validation/rejection paths, reembed-needed detection against
  fakes) and integration tests (real DB: schema update lands, bulk re-embed lands, search
  ranks on the new text afterward, a mid-batch embedder failure leaves everything
  unchanged).

## Scope & Constraints

- In scope: the four allowed changes from PRD §7.3, in any combination, in one command
  invocation; a pre-flight y/N confirmation with `--yes` bypass when a re-embed is coming;
  a progress bar for the re-embed pass.
- Out of scope (rejected, not just deferred): removing a field, adding a required field,
  changing a field's type, removing an enum value — PRD §7.3 is explicit that these need a
  coercion strategy this project isn't building for v1. No wizard/TTY mode for this
  command — it's a rare admin operation, not the hand-entry loop `add`/`create` optimize
  for; `collection edit products` with no flags errors naming the available flags.
- Hard constraint: a failed re-embed (Ollama down, dimension mismatch) must not leave the
  schema and the records' rendered/vector describing different states of the world —
  same invariant M8 established for a single record, extended to "all records in the
  collection."
- Trade-off: add-field unconditionally triggers a full re-render + re-embed pass, even
  though a newly added *optional* field is absent from every existing payload and so
  `render()` produces byte-identical text for old records (absent optional fields are
  skipped — `rendering.py:21-23`). PRD §7.3 says "re-render + re-embed all records" for
  this row without qualification, and diffing rendered-text-before-vs-after per record
  (to skip the no-op ones) is exactly the kind of per-record cleverness M8's `edit_record`
  already does for one record — duplicating it here for a rare bulk op is not worth the
  extra branch. Cost is bounded because R5a already prices this in: "corpus is small by
  design."

## Architecture & Design

### High-Level Flow

```
collection edit products --embed year --add-field "notes:text" --yes
        │
        ▼
EditCollection.execute(EditCollectionCommand, on_progress)
        │
        ├─ collections.get(name)                       → CollectionNotFoundError if missing
        ├─ reject any add_field with required=True      → UnsupportedSchemaChangeError
        ├─ apply embed_on/embed_off to existing fields   → UnknownFieldError if field missing
        │     (field.model_copy(update={"embed": ...}))
        ├─ apply enum_additions to existing enum fields  → UnknownFieldError / SchemaError
        │     (field.model_copy(update={"enum_values": old + new}))
        ├─ append add_fields to the field list
        ├─ CollectionSchema(fields=...)                  → re-runs every existing structural
        │                                                   check (dup names, dup enum
        │                                                   values, "must have >=1 embed
        │                                                   field") for free
        ├─ rename collision check (collections.get(new_name))  → DuplicateCollectionError
        │
        ├─ reembed_needed = add_fields or embed_on or embed_off
        │
        ├─ reembed_needed == False:
        │     collections.update(Collection(id, new_name, new_schema))   ← done
        │
        └─ reembed_needed == True:
              ├─ records.count(id) / records.list(id, limit=count, offset=0)   [read-only]
              ├─ for each batch of REEMBED_BATCH_SIZE records:
              │     texts = [render(new_schema, r.payload) for r in batch]
              │     vecs = await embedder.embed(texts)     ← may raise; nothing written yet
              │     on_progress(batches_done, total_batches)
              ├─ records.update_all([(Record(..., rendered=text), vec), ...])  ← one txn,
              │                                                   all-or-nothing
              └─ collections.update(Collection(id, new_name, new_schema))      ← committed
                                                                   last, see rationale below
```

### Key Changes

- **`src/semantic_db/domain/errors.py`**: add
  ```python
  class UnsupportedSchemaChangeError(SemanticDbError):
      """A schema change v1 deliberately rejects (PRD 7.3)."""
      def __init__(self, message: str) -> None:
          super().__init__(f"{message}; delete and recreate the collection instead")
  ```
  Used only for "add a required field" — the other three rejected changes (remove field,
  change type, remove enum value) have no flag that could express them, so there's
  nothing to guard.

- **`src/semantic_db/application/ports.py`**:
  - `CollectionRepository.update(self, collection: Collection) -> Collection`.
  - `RecordRepository.update_all(self, updates: Sequence[tuple[Record, list[float]]]) -> None`
    — bulk write for the re-embed pass; one transaction, all rows or none. Distinct from
    `update()` (M8, one record, `vec` optional) because every M9 re-embed call always has
    a fresh vector for every row — no "skip the embed" branch to carry here.

- **`src/semantic_db/application/use_cases/edit_collection.py`** (new):
  `EditCollectionCommand` (`name`, `rename_to: str | None`,
  `add_fields: Sequence[FieldDefinition]`, `embed_on: frozenset[str]`,
  `embed_off: frozenset[str]`, `enum_additions: Mapping[str, tuple[str, ...]]`) and
  `EditCollectionResult` (`collection: Collection`, `reembedded_count: int`).
  `EditCollection.execute(cmd, on_progress: Callable[[int, int], None] | None = None)`
  implements the flow above. `on_progress` is a plain callable (no Rich import here —
  `application` stays framework-free per the import-linter contract); the CLI supplies a
  closure that updates a `rich.progress.Progress` bar.
  `REEMBED_BATCH_SIZE = 32` module constant (Ollama batches through `/api/embed`, same
  endpoint `OllamaEmbeddingProvider` already calls — batching bounds one HTTP payload/
  timeout instead of shipping the whole corpus in one request).

- **`src/semantic_db/infrastructure/repositories.py`**:
  - `SqlCollectionRepository.update`: `UPDATE collections SET name=.., schema=..
    WHERE id=..`, wrapped in the same unique-violation-to-`DuplicateCollectionError`
    catch `create` already uses (belt-and-suspenders under the use case's own
    pre-check — a concurrent rename from another process is the only way to still hit
    the DB constraint).
  - `SqlRecordRepository.update_all`: one `session.begin()`, looping
    `sa_update(RecordModel)...` + `sa_update(EmbeddingModel)...` per item — same
    statements `update()` already issues, just N times inside one transaction instead of
    N separate transactions.

- **`src/semantic_db/cli/field_spec.py`**: add
  `parse_enum_add_specs(specs: list[str]) -> dict[str, tuple[str, ...]]` — splits each
  `field=value` on the first `=`, groups repeated `--enum-add category=drills
  --enum-add category=saws` into `{"category": ("drills", "saws")}`. Can't reuse
  `parse_set_specs` (`set_spec.py`) because that rejects a repeated key outright; here a
  repeated key is the normal way to add more than one value to the same field.

- **`src/semantic_db/cli/commands/collection.py`**: new `edit` command:
  ```
  collection edit <name> [--rename NEW_NAME]
                         [--add-field SPEC]...   (same grammar as `create`'s --field)
                         [--embed FIELD]...
                         [--no-embed FIELD]...
                         [--enum-add FIELD=VALUE]...
                         [--yes]
  ```
  - No flag given at all → `SemanticDbError` naming the five flags (mirrors `add`/`edit`'s
    no-TTY guard message style).
  - A field name in both `--embed` and `--no-embed` → rejected before calling the use
    case (mirrors `record edit`'s `--set`/`--unset` collision guard,
    `cli/commands/record.py:106-110`).
  - Parse `--add-field` specs with the existing `parse_field_spec` (`cli/field_spec.py`)
    — reused as-is; the required-field rejection happens once, in the use case, not
    duplicated in CLI parsing.
  - Build `EditCollectionCommand`, then:
    - if none of `add_field`/`embed`/`no_embed` given → no re-embed coming, call the use
      case directly, print `✓ updated collection '{name}'`.
    - else → fetch `record_count = queries.collection_stats(name)[1]` first (for the
      confirmation line and the progress bar's total), print
      `This changes collection '{name}': {record_count} records will be re-rendered and
      re-embedded.`, `typer.confirm` (skipped by `--yes`) — same reasoning M7 documented
      for using `typer.confirm`/`click.prompt` over `prompts.confirm()`: it has to be
      driveable by `CliRunner(input=...)` in integration tests, and `prompts.confirm()`
      needs a real TTY. Then open a `rich.progress.Progress` context, pass a closure as
      `on_progress`, run the use case, print
      `✓ updated collection '{name}', re-embedded {n} records with {model} ({ms}ms)`.

- **`src/semantic_db/container.py`**: wire `edit_collection: EditCollection` into
  `Container` (constructed with `collections`, `records`, `embedder` — same three
  dependencies `EditRecord` already takes).

- **No migration.** `collections.schema` and `records.rendered`/`embeddings.vec` already
  accept anything the domain model produces; renaming and schema edits are pure JSONB/text
  writes, no DDL change.

### Alternative Approaches Considered

- **Write order for the reembed path: records `update_all` first, then
  `collections.update` last (chosen)** vs. schema first, records last: there's no shared
  transaction across `SqlCollectionRepository` and `SqlRecordRepository` today (each opens
  its own session — same as every other use case in this codebase; `DeleteCollection`
  relies on the FK cascade being one statement, not an app-level saga), so a crash between
  the two writes is a real, if narrow, window. Records-first means that if the process
  dies right after `update_all` commits but before `collections.update` does, every
  record's `rendered` and vector are already mutually consistent with each other (just not
  yet with the schema's flags) — `search` still ranks correctly against what's actually
  stored. Schema-first would instead leave the schema claiming (say) `embed: true` on a
  field while the stored vectors still reflect the old text — a `search`-visible
  inconsistency, which is the worse failure mode. Not a full fix (a truly atomic
  cross-table commit would need a saga or moving both repositories onto one shared
  session, which no other use case in this codebase does either) — documented as a
  residual risk below rather than built out, consistent with R4 ("Clean Architecture
  becomes ceremony at this size").
- **Unconditional re-embed on add-field vs. diffing rendered text before/after per
  record**: covered under Scope & Constraints' trade-off above — chosen for uniformity
  with PRD §7.3's literal wording over the extra branch.
- **`--embed`/`--no-embed` as two flags vs. one `--toggle-embed FIELD` that flips
  whatever the current value is**: two explicit flags, because a toggle's outcome depends
  on state the caller can't see from the command line alone (is it currently on?),
  which makes a scripted/idempotent call impossible — you'd have to `show` first to know
  what `edit` will do. Explicit `--embed`/`--no-embed` is idempotent: calling `--embed
  year` twice is a no-op the second time.
- **No wizard for M9 (chosen)**: per your answer — this is a rare admin op, not the
  hand-entry loop `add`/`create`'s wizards optimize for. Flags-only keeps the surface
  small; a bare `collection edit products` errors naming the flags instead of silently
  waiting on a TTY prompt nothing will answer (same failure style `record add` already
  uses for its no-TTY guard).
- **Confirmation only when a re-embed is coming (chosen)** vs. always confirming any
  edit: rename and enum-add touch one row and no records — PRD's "the command says so
  before starting" language (§7.3) is specifically about the re-embed cost, so gating the
  prompt on `reembed_needed` avoids a pointless confirm on the cheap paths.

## Implementation Steps

1. `UnsupportedSchemaChangeError` in `domain/errors.py`.
2. `CollectionRepository.update` port method (`ports.py`) +
   `SqlCollectionRepository.update` (`repositories.py`) + integration test in
   `tests/integration/test_repositories.py` (rename lands; schema change lands; rename
   collision raises `DuplicateCollectionError`).
3. `RecordRepository.update_all` port method (`ports.py`) +
   `SqlRecordRepository.update_all` (`repositories.py`) + integration test (N records'
   `rendered`/`vec` all land in one call; nothing lands if the call is never made —
   i.e. there's no partial-write path to test *within* the method itself, since it's one
   `session.begin()`).
4. `parse_enum_add_specs` in `cli/field_spec.py` + unit test (grouping repeated keys,
   rejecting a blank field/value).
5. `EditCollectionCommand` / `EditCollectionResult` / `EditCollection` use case
   (`edit_collection.py`) + unit tests in `tests/unit/test_use_cases.py` against fakes:
   - rename alone → `collections.update` called with new name, same schema;
     `records`/`embedder` never touched.
   - `--add-field` with `required=True` → `UnsupportedSchemaChangeError`, nothing called.
   - `--add-field` optional → `reembed_needed=True`; embedder called once per batch of
     existing records with `render(new_schema, ...)` text.
   - `--embed`/`--no-embed` on an unknown field → `UnknownFieldError`.
   - `--embed` and `--no-embed` on the same field in one command → covered at the CLI
     layer (step 6), not here — the use case takes disjoint sets by construction from its
     command dataclass; add one unit test asserting behavior if a caller *did* construct
     overlapping sets (embed_off wins, since it's applied second) so the use case has a
     defined answer even though the CLI never lets it happen.
   - `--enum-add` on a non-enum field → `SchemaError`.
   - `--enum-add` on an enum field → new value appended, `reembed_needed=False`
     (`collections.update` called, embedder never touched).
   - `--enum-add` a value that already exists → `SchemaError` (via
     `CollectionSchema`'s own duplicate-enum-value check — no bespoke check needed).
   - embedder raising mid-batch (fake that fails on batch 2 of 3) →
     `records.update_all` never called, `collections.update` never called — full
     abort, nothing written.
   - zero existing records + `reembed_needed=True` (e.g. add-field on an empty
     collection) → `update_all` called with an empty list (or skipped entirely — pick
     whichever reads cleaner) and `collections.update` still runs.
6. Wire `edit_collection` into `Container`.
7. `collection edit` CLI command (`cli/commands/collection.py`): flag parsing, no-flags
   guard, `--embed`/`--no-embed` collision guard, confirmation + progress bar path,
   direct path when no re-embed is coming.
8. Unit tests in `tests/unit/test_cli.py`: no-flags error, collision error, `--add-field`
   spec parsing errors surface the same as `create`'s.
9. Integration tests in `tests/integration/test_cli_end_to_end.py`:
   - `--rename` → `collection show` under the new name returns the same records;
     old name now 404s (`CollectionNotFoundError`).
   - `--add-field "notes:text"` on a populated collection → `collection show` lists the
     new field; existing records' `rendered` unchanged (byte-for-byte — proves the
     unconditional-reembed trade-off doesn't corrupt anything even though it recomputed).
   - `--embed year` on `products` → re-run `search` with a query that only matches on the
     year text; ranking changes versus before the toggle (proves the re-embed actually
     used the new render, not a cached one).
   - `--enum-add category=drills` → `record add --set category=drills` now succeeds
     (previously would've been rejected as an invalid enum value).
   - `--add-field "sku:text:required"` → rejected, DB schema unchanged (`collection show`
     still shows the old field count).
   - Confirmation flow via `CliRunner(input=...)` (`y` and `n`), same pattern M7 uses for
     `collection delete`'s typed-name confirm.
   - `--yes` skips the prompt.
10. Update `README.md` status line and `PRD.md`'s milestone table (`M9` → done) and
    §10.1/§12.1 deviations if anything here ends up diverging from this plan the way M8
    diverged from its own PRD section (it didn't, but check).

### Risks & Mitigations

- **Risk:** crash between `records.update_all` committing and `collections.update`
  committing leaves the schema one step behind the records it describes.
  - Mitigation: as argued in Alternative Approaches, this ordering makes the
    records/vectors internally consistent with each other even in that window, which is
    the state `search` actually depends on. Documented as a residual limitation
    consistent with the codebase's existing stance on cross-repository atomicity (no
    other use case has it either) rather than built out with a saga.
  - Mitigation: re-running the same `collection edit` command is safe for `--embed`/
    `--no-embed`/`--enum-add` (idempotent) but **not** for `--add-field` (duplicate name
    error on retry) — call this out in the command's error message if `update_all`
    succeeded but `collections.update` then fails with a duplicate-name-style error,
    so the operator knows to retry without `--add-field`. (Nice-to-have; skip if it
    complicates the happy path — the crash window itself is the rare case.)

- **Risk:** `render(new_schema, r.payload)` for an existing record raises because the
  payload doesn't validate against the *new* schema (shouldn't happen for the four
  allowed changes, since none of them can invalidate an existing payload — that's exactly
  why required-field-add and type-change are the rejected ones — but worth a test).
  - Mitigation: unit test rendering every fixture record (`PRODUCTS`, `BOOKS` from
    `tests/schemas.py`) through a schema with each of the three allowed changes applied,
    confirming no exception and only the expected text delta.

- **Risk:** `REEMBED_BATCH_SIZE = 32` is a guess; too large risks the same
  `EMBED_TIMEOUT_SECONDS = 60.0` pressure `OllamaEmbeddingProvider` already has to guard
  against for one batch, too small makes the progress bar chatty for a big corpus.
  - Mitigation: not tunable via a flag for v1 (no evidence yet it needs to be); revisit
    with real corpus sizes. Integration test with a collection of ~100 records exercises
    at least 3 batches, so the loop and progress reporting are proven, not just the
    single-batch path.

- **Risk:** the `on_progress` callback threading a plain `Callable` through the use case
  reads like a framework leak into `application`.
  - Mitigation: it's a plain function type, not a Rich import — `import-linter`'s
    "no framework imports in application" contract is about *imports*, and this adds
    none. Confirm the `architecture` CI job still passes after this lands (same gate M0
    set up).

## Test Strategy

- **Unit:** `test_use_cases.py` (`EditCollection` against fakes — every rejection path,
  reembed-needed detection, batch-failure-aborts-everything), `test_field_spec.py`
  (`parse_enum_add_specs`), `test_cli.py` (no-flags guard, embed/no-embed collision).
- **Integration:** `test_repositories.py` (`SqlCollectionRepository.update`,
  `SqlRecordRepository.update_all` against real Postgres), `test_cli_end_to_end.py` (full
  `collection edit` flows for all four allowed changes plus all rejected ones, confirming
  both the DB state and, for embed-toggle, a `search` result change).
- **Manual:** run `collection edit` against `products` and `books` — add an optional
  field to each, toggle `embed` on an existing field, add an enum value to `category`, and
  attempt each of the four rejected changes to read the actual error text.

## Success Checklist

- [ ] All success criteria met (with test evidence)
- [ ] Unit + integration tests passing
- [ ] `CollectionRepository.update` and `RecordRepository.update_all` implemented and
  tested against real Postgres
- [ ] `collection edit`: rename, add-field, embed-toggle, enum-add all working; the four
  rejected changes fail with a clear reason
- [ ] Progress bar and confirmation prompt (with `--yes` bypass) working for the
  reembed path
- [ ] A mid-batch embedder failure proven (integration test) to leave the DB untouched
- [ ] `README.md` and `PRD.md` milestone table updated to mark M9 done
- [ ] No regressions in `create`/`list`/`show`/`delete`/`add`/`edit`/`search` (existing
  suite green)

## Timeline & Estimates

- Phase 1 (ports + repositories + migration-free schema/record bulk writes): ~2h
- Phase 2 (use case: validation, field-list surgery, batch re-embed loop): ~2.5h
- Phase 3 (CLI command: flags, confirmation, progress bar, container wiring): ~1.5h
- Phase 4 (unit + integration tests): ~2.5h
- Phase 5 (docs, manual pass, polish): ~0.5h
- **Total:** ~9h, plus buffer — this is PRD's own "genuinely hard command," and the
  batch-abort-on-failure path is the part most likely to eat the buffer.

## Open Questions

None outstanding — resolved during grilling:
- CLI grammar → mirror `record edit`'s flag style: `--rename`, `--add-field` (repeatable,
  same spec grammar as `create`), `--embed`/`--no-embed` (repeatable), `--enum-add`
  (repeatable, `field=value`); all combinable in one call.
- Wizard → none for M9; flags-only, no-flags-given errors naming them.
- Re-embed confirmation → y/N stating record count, `--yes` bypass, gated on whether a
  re-embed is actually coming (rename/enum-add alone skip it).
- Bulk re-embed batching → chunked (`REEMBED_BATCH_SIZE = 32`) with a Rich progress bar,
  not one giant `embed()` call.
