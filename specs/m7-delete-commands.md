# M7 — Delete Commands — Implementation Plan

## Summary

M7 adds `record delete` and `collection delete`, the last pieces needed to manage a corpus without dropping to `psql`. Both are destructive and irreversible, so the PRD (§7.4) requires them to be covered by integration tests, not just unit tests against fakes — this plan's biggest decision is making that testable at all.

## Success Criteria

- `semantic-db record delete <collection> <id>` removes the record and its embedding row (FK cascade); confirms `y/N` unless `--yes`.
- `semantic-db collection delete <name>` removes the collection, its records, and their embeddings (FK cascade); prints what will be destroyed and requires typing the collection name to confirm, unless `--yes`.
- Deleting a record/collection that doesn't exist fails with the existing `RecordNotFoundError` / `CollectionNotFoundError`, exit code 2 — no silent no-op.
- Both confirmation flows (`y/N` and typed-name) are exercised by integration tests via `CliRunner(input=...)`, not just the `--yes` bypass.
- `import-linter`, `mypy --strict`, `ruff`, unit suite, and integration suite all green.

## Scope & Constraints

- In scope: `record delete`, `collection delete`, their use cases, repository methods, CLI wiring, tests.
- Out of scope: soft delete / undo, bulk delete, `record edit` (M8), `collection edit` (M9).
- Hard constraint: deletion must go through the existing FK `ON DELETE CASCADE` (already in `models.py` for both `records.collection_id` and `embeddings.record_id`) — no new migration needed.
- Build order (per discussion): `record delete` first (simpler, de-risks the confirm-prompt approach), then `collection delete` (cascade + typed confirm).
- Test scope (per discussion): unit tests for the new use cases against fakes (matches §9.2, same as every other use case) + integration tests via `CliRunner` for the full command including both confirmation flows. No new entries in `tests/unit/test_cli.py` (that file is flag-path-only, no-DB — not relevant here since delete has no flag-only validation to check pre-DB).

## Architecture & Design

### High-Level Flow

```
record delete products 42
  → guard(): parse args
  → confirm "Delete record 42 from 'products'? [y/N]" (skipped if --yes)
  → DeleteRecord.execute(cmd) → CollectionRepository.get (404 check) → RecordRepository.delete
  → "✓ deleted record 42"

collection delete products
  → guard(): parse args
  → Queries.collection_stats("products") → (field_count, record_count)  [404 check happens here]
  → print "This deletes collection 'products': 5 fields, 312 records, 312 embeddings."
  → typed-name confirm: "Type the collection name to confirm: " (skipped if --yes)
  → DeleteCollection.execute(cmd) → CollectionRepository.delete
  → "✓ deleted"
```

Embeddings count is printed as equal to record count rather than queried separately: `AddRecord` embeds atomically on save (PRD §5.1), so "a record with no vector" is not a reachable state — no new port method needed to count embeddings.

### Key Changes

- **`application/ports.py`**: add to `CollectionRepository`: `async def delete(self, name: str) -> None: ...  # M7`. Add to `RecordRepository`: `async def delete(self, collection_id: int, record_id: int) -> None: ...  # M7`.
- **`application/use_cases/delete_record.py`** (new): `DeleteRecordCommand(collection_name, record_id)` + `DeleteRecord`. Looks up the collection (404 if missing), looks up the record via `records.get` (404 if missing — needed because a bare SQL `DELETE` matching 0 rows gives no signal), then deletes.
- **`application/use_cases/delete_collection.py`** (new): `DeleteCollectionCommand(name)` + `DeleteCollection`. Looks up the collection (404 if missing), then deletes. Cascade handles records/embeddings.
- **`application/queries.py`**: add `collection_stats(name) -> tuple[int, int]` (field_count, record_count) — reuses `get_collection` and the existing `RecordRepository.count` (M6), for the CLI's pre-delete summary line.
- **`infrastructure/repositories.py`**:
  - `SqlCollectionRepository.delete(name)`: `DELETE FROM collections WHERE name = :name`.
  - `SqlRecordRepository.delete(collection_id, record_id)`: `DELETE FROM records WHERE id = :id AND collection_id = :collection_id`.
- **`cli/prompts.py`**: no new multiline/completion logic needed — see the library decision below instead of extending this module.
- **`cli/commands/record.py`**: `record delete <collection> <record_id> [--yes]`.
- **`cli/commands/collection.py`**: `collection delete <name> [--yes]`.
- **`container.py`**: wire `delete_record = DeleteRecord(collections, records)` and `delete_collection = DeleteCollection(collections)`.

### Design decision: confirmation prompts use `typer.confirm` / `click.prompt`, not the existing `prompts.confirm()`

The existing `confirm()` helper (`cli/prompts.py`) is built on `prompt_toolkit.PromptSession`, which needs a real TTY — that's exactly why `record add`'s interactive path currently refuses to run without one (§12.1 deviation). None of today's tests exercise it through `CliRunner`; `record add`'s tests always take the `--set` flag path for that reason.

PRD's done-when for M7 is "destructive paths covered by integration tests" — that has to include the confirmation logic itself (a wrong typed name aborting, a bare-Enter y/N defaulting to no), not just the `--yes` bypass. `typer.confirm()` and `click.prompt()` are built on Click's prompt machinery, which `CliRunner(input=...)` drives directly — this is the standard way Click/Typer apps are tested. Delete confirmations don't need prompt_toolkit's multiline input or tab-completion, so there's no feature loss, and it makes the whole flow testable without a TTY guard workaround.

This will be the first place in the codebase using `CliRunner(input=...)`. Flagging it since it's a small precedent-setting choice, not just a local implementation detail.

### Alternative Approaches Considered

- **Reuse `prompts.confirm()` as-is, require `--yes` outside a TTY** (mirrors `record add`'s pattern): rejected — it would leave the actual confirm/typed-name logic untested by integration tests, only the bypass. Fails the PRD's stated done-when more literally than the alternative.
- **Add a new port method for embeddings count**: rejected — embeddings count always equals record count under the current invariant (embed-on-save, no partial state); a second query would just restate `RecordRepository.count`.
- **Soft delete (tombstone row)**: rejected — not in PRD scope for v1, adds a query-filtering concern everywhere reads happen for no stated requirement.

## Implementation Steps

1. `application/ports.py` — add `delete` to both `CollectionRepository` and `RecordRepository` protocols.
2. `tests/fakes.py` — add `delete` to `InMemoryRecordRepository` and `InMemoryCollectionRepository`.
3. `application/use_cases/delete_record.py` — `DeleteRecordCommand` + `DeleteRecord` (404 on missing collection or record, else delete).
4. `tests/unit/test_use_cases.py` — unit tests for `DeleteRecord`: deletes the target, leaves other records untouched, 404 on unknown collection, 404 on unknown record id.
5. `infrastructure/repositories.py` — `SqlRecordRepository.delete`.
6. `container.py` — wire `delete_record`.
7. `cli/commands/record.py` — `record delete <collection> <record_id> [--yes]` using `typer.confirm`.
8. `tests/integration/test_cli_end_to_end.py` — record delete: removes the record and its embedding row, `--yes` skips the prompt, typed "n" aborts without deleting, 404 on unknown id/collection.
9. `application/use_cases/delete_collection.py` — `DeleteCollectionCommand` + `DeleteCollection` (404 on missing name, else delete).
10. `tests/unit/test_use_cases.py` — unit tests for `DeleteCollection`: deletes, 404 on unknown name.
11. `application/queries.py` — `collection_stats(name) -> tuple[int, int]`.
12. `tests/unit/test_queries.py` — unit test for `collection_stats`.
13. `infrastructure/repositories.py` — `SqlCollectionRepository.delete`.
14. `container.py` — wire `delete_collection`.
15. `cli/commands/collection.py` — `collection delete <name> [--yes]`: print stats line, `click.prompt` for typed-name confirm, delete, success message.
16. `tests/integration/test_cli_end_to_end.py` — collection delete: cascade removes records + embeddings (query both tables post-delete), typed-name mismatch aborts without deleting, `--yes` skips display+prompt, 404 on unknown name.
17. `PRD.md` — flip M7 to **done** in §12, note the `typer.confirm`/`click.prompt` choice in §12.1 deviations.
18. Full gate: `ruff check`, `ruff format --check`, `mypy --strict`, `lint-imports`, `pytest -m "not integration"`, `pytest -m integration`.

## Risks & Mitigations

- **Risk:** `click.prompt`/`CliRunner(input=...)` doesn't behave the way assumed (e.g. EOF handling, prompt text matching) once actually run.
  - Mitigation: step 7/8 (record delete) is deliberately first and smaller — if the prompt-testing approach has a problem, it surfaces there before collection delete's more complex typed-confirm is built on top of it.
- **Risk:** Deleting a record/collection that's mid-search (unlikely at this scale, single local user) races a read.
  - Mitigation: not mitigated — out of scope, matches the project's "corpus is small, local, single-user" framing throughout the PRD.
- **Risk:** Typed-name confirm is case- or whitespace-sensitive in a way that's annoying in practice.
  - Mitigation: exact match against the stored name, no trimming beyond stripping surrounding whitespace — matches `collection create`'s existing input handling style.

## Test Strategy

- Unit: `DeleteRecord`, `DeleteCollection` against `InMemory*Repository` fakes (no DB) — happy path + both 404s.
- Unit: `Queries.collection_stats` against fakes.
- Integration: full CLI flow via `CliRunner`, `pgvector/pgvector:pg17` — cascade verified by querying `RecordModel`/`EmbeddingModel` directly after delete; both confirmation flows (accept and decline) driven via `input=`; `--yes` path.
- No manual testing beyond running the two commands once by hand after the automated suite passes.

## Success Checklist

- [ ] `record delete` and `collection delete` implemented, wired, documented in `--help`.
- [ ] Unit + integration suites green, including both confirm-prompt branches.
- [ ] `ruff`, `mypy --strict`, `lint-imports` green.
- [ ] PRD §12 and §12.1 updated to reflect M7 done and the confirm-library deviation.
- [ ] No regression in M1–M6 commands (full suite run, not just new tests).

## Timeline & Estimates

- Record delete (steps 1–8): ~1.5h
- Collection delete (steps 9–16): ~2h
- PRD update + full gate + fixes (steps 17–18): ~0.5h
- **Total:** ~4h, plus buffer for the `CliRunner(input=...)` precedent if it needs iteration.

## Open Questions

None outstanding — resolved during grilling: `--yes` added to `record delete`; build order is record-then-collection; test scope is unit (fakes) + integration (CliRunner+DB), no new flag-path-only CLI unit tests.
