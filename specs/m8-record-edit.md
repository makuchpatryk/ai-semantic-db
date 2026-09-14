# M8: `record edit` — Implementation Plan

## Summary

M8 adds `record edit`, the last hole in single-record management (add/list/show/delete
already ship). Editing must keep `payload`, `rendered`, and the embedding vector
consistent — the same invariant M5's `add` established (PRD §5.1: a record without a
matching vector is invisible to search, and that must never be a reachable state).

## Success Criteria

- `record edit <collection> <id> --set k=v [--set k=v ...] [--unset k ...]` updates any
  subset of fields, re-validates the full merged payload, and re-renders it.
- Re-embed happens iff a field with `embed: true` actually changed value (added,
  changed, or unset). Editing only non-embedded fields leaves the stored vector
  untouched — no wasted Ollama calls.
- If embedding fails (Ollama down, dimension mismatch), the DB is untouched — no
  partial write of payload/rendered without a matching vector, and no stale vector
  against new rendered text.
- No `--set`/`--unset` on a TTY launches a wizard pre-filled with the record's current
  values (reusing the same prompt path `add` already has), matching `add`'s UX.
- `record edit` covered by unit tests (merge logic, re-embed skip/trigger, failure
  aborts before any write) and integration tests (real DB: payload/rendered/vec land
  atomically; non-embed edit provably leaves the vector unchanged).

## Scope & Constraints

- In scope: single-record edit by id, partial update via `--set`, field clearing via
  `--unset`, wizard mode, atomic re-render/re-embed.
- Out of scope: bulk edit, editing across collections, collection schema edit (M9),
  edit history/audit log, embedding-model migration on edit (search already handles
  cross-model detection independently — PRD §9.1).
- Hard constraint: never let `records.rendered` and the stored vector diverge, and
  never let a record exist with payload changed but old rendered/vector still applied
  (partial write). Same bar M5's `add` and M7's `delete` already meet.
- Trade-off: record lookup is by numeric `id` only, not a "natural key" — the schema
  model (`FieldDefinition`) has no unique/key concept anywhere in the codebase (`list`,
  `show`, `delete` are all id-only too), so inventing one for `edit` alone would be
  scope the rest of the CLI doesn't support. This overrides the earlier assumption that
  a natural key might exist.

## Architecture & Design

### High-Level Flow

```
record edit products 42 --set price=4300
        │
        ▼
EditRecord.execute(EditRecordCommand)
        │
        ├─ collections.get(name)              → CollectionNotFoundError if missing
        ├─ records.get(collection_id, id)      → RecordNotFoundError if missing
        ├─ merge: existing.payload + --set overrides − --unset keys
        ├─ coerce_payload(schema, merged)      → full re-validation (required fields
        │                                         checked over the MERGED payload, so
        │                                         unsetting a required field errors)
        ├─ render(schema, payload)             → new rendered text
        ├─ diff embed-flagged fields old vs new
        │     unchanged → vec = None (skip embed call)
        │     changed   → vec = embed_one(embedder, rendered)   [may raise, nothing
        │                                                         written yet]
        └─ records.update(Record(id, collection_id, payload, rendered), vec)
                 → one transaction: UPDATE records (+ UPDATE embeddings iff vec given)
```

### Key Changes

- **`src/semantic_db/application/use_cases/edit_record.py`** (new): `EditRecordCommand`
  (`collection_name`, `record_id`, `set_values: Mapping[str, object]`,
  `unset_fields: frozenset[str]`) and `EditRecord`, mirroring `AddRecord`'s shape.
  Merge step: start from `dict(existing.record.payload)`, apply `set_values` (raw,
  coerced same as `--set` today), then `del` each `unset_fields` key. Re-embed decision
  compares `old.payload.get(f.name)` vs `new_payload.get(f.name)` for every
  `f in schema.fields if f.embed`.

- **`src/semantic_db/application/ports.py`**: add
  `async def update(self, record: Record, vec: list[float] | None) -> Record: ...  # M8`
  to `RecordRepository`. `vec=None` means "leave the stored embedding row untouched."

- **`src/semantic_db/infrastructure/repositories.py`**: `SqlRecordRepository.update`.
  One `session.begin()`: `UPDATE records SET payload=.., rendered=.. WHERE id=.. AND
  collection_id=..`; if `vec is not None`, also `UPDATE embeddings SET model=.., vec=..
  WHERE record_id=..` in the same transaction. No upsert branch — `add` always creates
  the embeddings row, so by the time `edit` runs it's guaranteed present.

- **`src/semantic_db/cli/commands/record.py`**: new `edit` command, same shape as
  `add`/`delete`:
  ```
  record edit <collection> <id> [--set k=v ...] [--unset k ...] [--yes]
  ```
  - `--set`/`--unset` given → non-interactive path, build the command, run it, print
    `Panel(rendered, title="Saved")` + a `✓ updated record {id}` line noting whether it
    re-embedded (mirrors `add`'s `_model_name()`/timing line; say
    "unchanged embedding" when `vec` was skipped).
  - Neither given + TTY → wizard: fetch current `RecordDetail`, call
    `prompt_record_values(schema, defaults=detail.record.payload)` (same function `add`
    already uses for its "sticky previous record" prefill — here the defaults are the
    record's *current* values instead). Preview via `preview_panel`, confirm via
    `confirm("Save?")`, same loop shape as `_add_interactive`. Clearing a prefilled
    field to empty in the wizard already means "omit" (existing `_is_blank` semantics
    in `coerce_payload`), so unset falls out for free in wizard mode — no separate
    wizard-only unset UI needed.
  - Neither given + no TTY → same `SemanticDbError` as `add`'s non-interactive guard.
  - A key in both `--set` and `--unset` → reject before calling the use case
    (`SemanticDbError`, same style as `parse_set_specs`'s duplicate-key check).

- **`src/semantic_db/cli/set_spec.py`**: add `parse_unset_specs(specs: list[str]) ->
  frozenset[str]` (trivial: strip, reject empty, reject duplicates) — or fold into a
  single new function if that reads cleaner once written; `parse_set_specs` stays as
  is for `--set`.

- **`src/semantic_db/container.py`**: wire `edit_record: EditRecord` into `Container`.

- **No schema/migration changes.** `records` and `embeddings` tables already have
  everything `update` needs (`records.payload`, `records.rendered`,
  `embeddings.vec`/`model`, `embeddings.record_id` as PK — confirmed one embedding row
  per record).

### Alternative Approaches Considered

- **Always re-embed on any edit** (simpler, no diff logic) vs **skip re-embed when no
  embedded field changed** (chosen, per your answer): the collection can have
  non-embedded fields (e.g. `year:int` without `embed`), and always re-embedding wastes
  an Ollama round trip and rewrites a vector to the exact same value. The diff is a
  handful of lines against the payload already fetched, so it's cheap correctness, not
  premature optimization.

- **Transaction-wraps-everything vs compute-then-write** (chosen): embedding calls
  Ollama over HTTP — that's not something you want inside a DB transaction (long-held
  locks, and Postgres can't roll back an HTTP call anyway). `add` already validates and
  renders before opening the transaction; `edit` follows the same order: merge →
  validate → render → embed (if needed) → **then** one short transaction for the
  writes. Matches your "reject whole edit, DB untouched" answer without needing DB
  rollback semantics to enforce it.

- **`--unset` flag vs blank `--set k=`** : `coerce_payload` already treats an empty
  string as "field absent" for a *fresh* payload (`_is_blank`), but `edit` merges onto
  an *existing* payload — if we reused `--set k=` for clearing, there'd be no way to
  express "leave this field alone" vs "clear it" for fields not mentioned at all,
  because both would need to be silently skipped by the CLI parser. An explicit
  `--unset` keeps the three states (touch, don't touch, clear) unambiguous, matching
  your answer.

- **Record lookup by natural key**: not implemented — see Scope & Constraints. `id`
  only, consistent with `show`/`list`/`delete`.

## Implementation Steps

1. `RecordRepository.update` port method (`ports.py`).
2. `SqlRecordRepository.update` (`repositories.py`) + integration test in
   `tests/integration/test_repositories.py` (update payload/rendered only, vec=None;
   update all three, vec given; confirm embeddings row's `vec`/`model` only changes
   when passed).
3. `parse_unset_specs` in `cli/set_spec.py` + unit test.
4. `EditRecordCommand` / `EditRecord` use case (`edit_record.py`) + unit tests in
   `tests/unit/test_use_cases.py`:
   - partial `--set` merges onto existing payload correctly
   - `--unset` on optional field removes it, re-render reflects that
   - `--unset` on required field raises `MissingRequiredFieldError`
   - unknown field in `--set`/`--unset` raises `UnknownFieldError`
   - editing only non-embed fields → embedder not called, `vec=None` passed to
     `records.update`
   - editing an embed field → embedder called once, its result passed through
   - embedder raising → `records.update` never called (use a fake repo, assert)
5. Wire `edit_record` into `Container`.
6. `record edit` CLI command (`cli/commands/record.py`): flag path, wizard path,
   no-TTY guard, `--set`/`--unset` key-collision guard.
7. Unit tests in `tests/unit/test_cli.py` for flag parsing / error paths (collision,
   no-TTY).
8. Integration tests in `tests/integration/test_cli_end_to_end.py`:
   - `add` then `edit --set` an embedded field → `search` ranks it by the new text, not
     the old.
   - `edit --set` a non-embedded field only → stored vector byte-identical to before.
   - `edit --unset` a required field → command exits non-zero with a clear message, DB
     row unchanged.
   - Wizard path via `CliRunner(input=...)`, same pattern M6/M7 already use.
9. Update `README.md` status line and `PRD.md` milestone table (`M8` → done, same as
   M7's entry).

### Risks & Mitigations

- **Risk:** merge step silently drops a field because of a JSONB round-trip quirk
  (e.g. `date` fields — `payload_from_jsonb` already special-cases these once read back
  from `RecordDetail`).
  - Mitigation: `records.get()` already returns a `Record` with `payload_from_jsonb`
    applied, so merge starts from properly-typed Python values (`date`, not `str`) —
    same types `coerce_value` already accepts as pass-through. Covered by step 4's
    unit tests using the `books` test schema (has a `date` field).

- **Risk:** re-embed diff compares old vs new by `==`, and float coercion
  (`4200` vs `4200.0`) makes an unedited field look "changed," triggering a needless
  re-embed.
  - Mitigation: both sides go through `coerce_payload`/`coerce_value` before the diff
    (old payload already coerced when stored; new payload freshly coerced), so both are
    the same Python type for the field. Add a unit test that edits an unrelated field
    and asserts an embed-typed float field with no `--set` for it does not trigger
    re-embed.

- **Risk:** partial failure between the `records` UPDATE and the `embeddings` UPDATE if
  something throws mid-transaction.
  - Mitigation: both statements execute inside the same `session.begin()` block,
    identical to how `add` already writes `RecordModel` + `EmbeddingModel` together.

- **Risk:** `--unset` on a field that was never set anyway — should this be an error or
  a no-op?
  - Mitigation: no-op (deleting an absent dict key is safe); don't special-case it,
    keep behavior predictable and scriptable.

- **Risk:** wizard mode showing stale defaults if `EDITOR`-style multi-step confirm
  loop resembles `add`'s "Add another?" loop and a copy-paste error re-adds records
  instead of editing.
  - Mitigation: `edit`'s wizard has no "another?" loop — it edits exactly the one
    record given on the command line and exits. Keep this asymmetry explicit in the
    command's docstring/help text.

## Test Strategy

- **Unit:** `test_use_cases.py` (`EditRecord` merge/validation/re-embed-diff logic
  against fakes — no DB, no network), `test_cli.py` (flag parsing, collision/no-TTY
  errors), `test_field_spec`/`test_validation` untouched (no schema changes).
- **Integration:** `test_repositories.py` (`SqlRecordRepository.update` against real
  Postgres — payload/rendered/vec land correctly, vec untouched when `None`),
  `test_cli_end_to_end.py` (full `record edit` CLI flow including a `search` after edit
  to prove re-embed actually changed ranking, and a vector-equality check to prove a
  non-embed edit did *not* re-embed).
- **Manual:** run `record edit` against the `products` and `books` test collections
  (PRD's second-collection check) — edit an embedded text field, an int field, an array
  field, and a bool field; confirm rendered text and `record show` output.

## Success Checklist

- [ ] All success criteria met (with test evidence)
- [ ] Unit + integration tests passing (`make test` / project's usual test command)
- [ ] `RecordRepository.update` and `SqlRecordRepository.update` implemented and tested
- [ ] `record edit` CLI command: flags, wizard, no-TTY guard, collision guard
- [ ] Non-embed-only edit proven to skip re-embed (integration test, not just unit)
- [ ] `README.md` and `PRD.md` milestone table updated to mark M8 done
- [ ] No regressions in `add`/`list`/`show`/`delete`/`search` (existing suite green)

## Timeline & Estimates

- Phase 1 (port + repo + use case + container wiring): ~2h
- Phase 2 (CLI command, flag + wizard paths): ~1.5h
- Phase 3 (unit + integration tests): ~2h
- Phase 4 (docs, manual pass, polish): ~0.5h
- **Total:** ~6h, plus buffer for any JSONB/date edge case surprises

## Open Questions

None outstanding — all resolved during grilling:
- edit scope → any field, any combo (`--set`, repeatable)
- embed failure handling → reject whole edit, DB untouched
- wizard → yes, pre-filled with current values
- no-op re-embed → skip when no embed-flagged field changed
- unset → explicit `--unset` flag
- validation → reuse existing `coerce_payload`/`render`, applied to the full merged
  payload
- record lookup → `id` only (corrected from "id or natural key" during code
  exploration — no natural-key concept exists anywhere in the schema model today)
