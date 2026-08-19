from typing import Any

import questionary

from semantic_db.cli.runner import console, error_console
from semantic_db.domain.collection import FieldDefinition
from semantic_db.domain.errors import SchemaError
from semantic_db.domain.field_types import UNIT_TYPES, FieldType

EMBED_LABEL = "embed in search text"
REQUIRED_LABEL = "required"


class PromptAborted(Exception):
    """The user cancelled a prompt (Ctrl-C / Ctrl-D)."""


def prompt_field_definitions() -> list[FieldDefinition]:
    """Collect field definitions interactively (PRD 4.2).

    Produces exactly the same list `--field` parsing produces — the wizard is an input
    adapter, never a second way to build a schema.
    """
    fields: list[FieldDefinition] = []
    while True:
        console.rule(f"[bold]Field {len(fields) + 1}")
        name = _ask_text("Field name:")
        if not name:
            return fields
        field = _prompt_one(name)
        if field is not None:
            fields.append(field)


def confirm(message: str, *, default: bool = False) -> bool:
    return bool(_ask(questionary.confirm(message, default=default)))


def _prompt_one(name: str) -> FieldDefinition | None:
    field_type = FieldType(
        _ask_text_from(
            questionary.select("Type:", choices=[str(t) for t in FieldType], default="string")
        )
    )

    enum_values: tuple[str, ...] | None = None
    if field_type is FieldType.ENUM:
        raw = _ask_text("Enum values (comma-separated):")
        enum_values = tuple(value.strip() for value in raw.split(",") if value.strip())

    unit: str | None = None
    if field_type in UNIT_TYPES:
        unit = _ask_text("Unit (optional, e.g. PLN):") or None

    options = _ask_choices(
        questionary.checkbox(
            "Options:",
            choices=[
                questionary.Choice(EMBED_LABEL, checked=True),
                questionary.Choice(REQUIRED_LABEL),
            ],
        )
    )

    try:
        return FieldDefinition(
            name=name,
            type=field_type,
            embed=EMBED_LABEL in options,
            required=REQUIRED_LABEL in options,
            enum_values=enum_values,
            unit=unit,
        )
    except SchemaError as exc:
        # Re-prompting the one bad field beats discarding the whole wizard.
        error_console.print(f"[bold red]Error:[/] {exc}")
        return None


def _ask(question: Any) -> Any:
    answer = question.ask()
    if answer is None:
        raise PromptAborted("cancelled")
    return answer


def _ask_text(message: str) -> str:
    return _ask_text_from(questionary.text(message))


def _ask_text_from(question: Any) -> str:
    return str(_ask(question)).strip()


def _ask_choices(question: Any) -> list[str]:
    return [str(choice) for choice in _ask(question)]
