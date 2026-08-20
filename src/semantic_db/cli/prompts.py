import os
import sys
from datetime import date
from typing import Any, cast

import questionary
from click import edit as click_edit

from semantic_db.cli.runner import console, error_console
from semantic_db.domain.collection import CollectionSchema, FieldDefinition
from semantic_db.domain.errors import PayloadValidationError, SchemaError
from semantic_db.domain.field_types import UNIT_TYPES, FieldType
from semantic_db.domain.record import Payload, PayloadValue
from semantic_db.domain.validation import coerce_value

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


def prompt_record_values(
    schema: CollectionSchema, defaults: dict[str, PayloadValue] | None = None
) -> Payload:
    """Collect record values interactively, with per-type input and re-prompt on error.

    Produces exactly the same Payload that `--set` would, except input is guided by type
    and defaults from the previous record sticky.
    """
    defaults = defaults or {}
    result: Payload = {}

    for field in schema.fields:
        while True:
            try:
                value = _prompt_field(field, defaults.get(field.name))
                if value is not None or not field.required:
                    if value is not None:
                        result[field.name] = value
                    break
                error_console.print(f"[bold red]Error:[/] field '{field.name}' is required")
            except PayloadValidationError as exc:
                error_console.print(f"[bold red]Error:[/] {exc}")

    return result


def confirm(message: str, *, default: bool = False) -> bool:
    return bool(_ask(questionary.confirm(message, default=default)))


def _prompt_one(name: str) -> FieldDefinition | None:
    field_type = FieldType(
        _ask_text_from(
            questionary.select("Type:", choices=[str(t) for t in FieldType], default="text")
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


def _prompt_field(
    field: FieldDefinition, prev_default: PayloadValue | None = None
) -> PayloadValue | None:
    """Prompt for a single field value, coercing and re-prompting on error."""
    label = f"{field.label}{'*' if field.required else ''}"
    if field.type in UNIT_TYPES and field.unit:
        label = f"{label} ({field.unit})"

    match field.type:
        case FieldType.TEXT:
            return _ask_text_field(label, prev_default)
        case FieldType.ENUM:
            return _ask_enum(label, field, prev_default)
        case FieldType.INT:
            return _ask_int_field(label, field, prev_default)
        case FieldType.FLOAT:
            return _ask_float_field(label, field, prev_default)
        case FieldType.BOOL:
            return _ask_bool_field(label, field, prev_default)
        case FieldType.DATE:
            return _ask_date_field(label, field, prev_default)
        case FieldType.ARRAY_STRING:
            return _ask_array_field(label, prev_default)
        case _:
            raise AssertionError(f"unknown field type {field.type}")


def _ask_text_field(label: str, prev: PayloadValue | None = None) -> str | None:
    """Prompt for a multiline text value, trying editor first."""
    default_text = str(prev) if prev else ""

    # Try click.edit() if we have a proper editor environment
    if _has_editor_env():
        try:
            result = click_edit(default_text)
            if result is not None:
                return result.strip() if result.strip() else None
        except Exception:
            pass

    # Fallback to multiline questionary
    raw = _ask_text_from(questionary.text(label, multiline=True, default=default_text))
    return raw if raw else None


def _has_editor_env() -> bool:
    """Check if we have an editor and a TTY to use it."""
    has_editor = bool(os.environ.get("EDITOR") or os.environ.get("VISUAL"))
    has_tty = sys.stdin.isatty()
    return has_editor and has_tty


def _ask_enum(label: str, field: FieldDefinition, prev: PayloadValue | None = None) -> str | None:
    """Prompt for an enum value."""
    enum_values = field.enum_values or ()
    choices = list(enum_values)
    if not field.required:
        choices = ["(skip)"] + choices

    default = str(prev) if prev and str(prev) in enum_values else None
    selected = _ask_text_from(questionary.select(label, choices=choices, default=default))

    if selected == "(skip)":
        return None
    return selected


def _ask_int_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> int | None:
    """Prompt for an int value."""
    default = str(int(prev)) if isinstance(prev, (int, float)) else None
    raw = _ask_text_from(questionary.text(label, default=default or ""))
    if not raw:
        return None
    return cast(int, coerce_value(field, raw))


def _ask_float_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> float | None:
    """Prompt for a float value."""
    default = str(float(prev)) if isinstance(prev, (int, float)) else None
    raw = _ask_text_from(questionary.text(label, default=default or ""))
    if not raw:
        return None
    return cast(float, coerce_value(field, raw))


def _ask_bool_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> bool | None:
    """Prompt for a bool value."""
    if field.required:
        return bool(_ask(questionary.confirm(label, default=bool(prev) if prev else False)))

    choices = ["yes", "no"]
    if not field.required:
        choices = ["(skip)"] + choices

    default = "yes" if prev else None
    selected = _ask_text_from(questionary.select(label, choices=choices, default=default))

    if selected == "(skip)":
        return None
    return cast(bool, coerce_value(field, selected))


def _ask_date_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> date | None:
    """Prompt for a date value."""
    default = prev.isoformat() if isinstance(prev, date) else None
    raw = _ask_text_from(questionary.text(label, default=default or ""))
    if not raw:
        return None
    return cast(date, coerce_value(field, raw))


def _ask_array_field(label: str, prev: PayloadValue | None = None) -> list[str] | None:
    """Prompt for an array<string> value."""
    default = ", ".join(prev) if isinstance(prev, list) else None
    raw = _ask_text_from(questionary.text(label, default=default or ""))
    if not raw:
        return None
    return cast(
        list[str],
        coerce_value(FieldDefinition(name="temp", type=FieldType.ARRAY_STRING), raw),
    )
