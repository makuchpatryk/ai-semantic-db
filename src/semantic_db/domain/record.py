from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

#: Every value that may live in a validated payload, i.e. in `records.payload` JSONB.
PayloadValue = str | int | float | bool | list[str] | date
Payload = dict[str, PayloadValue]


@dataclass(frozen=True)
class Record:
    """A validated record together with the exact text that was embedded."""

    collection_id: int
    payload: Mapping[str, PayloadValue]
    rendered: str
    id: int | None = None


@dataclass(frozen=True)
class ScoredRecord:
    """A search hit. Declared here so ports stay stable; first used by search (M5)."""

    record: Record
    score: float
