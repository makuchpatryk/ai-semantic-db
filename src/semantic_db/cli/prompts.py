from datetime import date
from typing import cast

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings

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
    is_first_field = True

    for field in schema.fields:
        while True:
            try:
                value = _prompt_field(field, defaults.get(field.name), is_first_field)
                is_first_field = False
                if value is not None or not field.required:
                    if value is not None:
                        result[field.name] = value
                    break
                error_console.print(f"[bold red]Error:[/] field '{field.name}' is required")
            except PayloadValidationError as exc:
                error_console.print(f"[bold red]Error:[/] {exc}")

    return result


def confirm(message: str, *, default: bool = False) -> bool:
    """Prompt yes/no with default."""
    session = PromptSession()
    default_str = "Y/n" if default else "y/N"
    answer = session.prompt(f"{message} [{default_str}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def _prompt_one(name: str) -> FieldDefinition | None:
    session = PromptSession()
    field_types = [str(t) for t in FieldType]
    completer = WordCompleter(field_types, ignore_case=True)

    field_type = FieldType(
        session.prompt(f"Type [{field_types[0]}]: ", completer=completer).strip() or "text"
    )

    enum_values: tuple[str, ...] | None = None
    if field_type is FieldType.ENUM:
        raw = session.prompt("Enum values (comma-separated): ").strip()
        enum_values = tuple(value.strip() for value in raw.split(",") if value.strip())

    unit: str | None = None
    if field_type in UNIT_TYPES:
        unit = session.prompt("Unit (optional, e.g. PLN): ").strip() or None

    console.print("Options: (press Space to toggle, Enter to confirm)")
    options = []
    for label in [EMBED_LABEL, REQUIRED_LABEL]:
        ans = session.prompt(f"  {label}? [Y/n]: ").strip().lower()
        if ans != "n":
            options.append(label)

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
        error_console.print(f"[bold red]Error:[/] {exc}")
        return None


def _ask_text(message: str) -> str:
    """Prompt for text."""
    session = PromptSession()
    return session.prompt(f"{message}: ").strip()


def _prompt_field(
    field: FieldDefinition,
    prev_default: PayloadValue | None = None,
    is_first: bool = False,
) -> PayloadValue | None:
    """Prompt for a single field value, coercing and re-prompting on error."""
    if is_first:
        console.print(
            "[dim]Text fields: Enter to finish, Alt+Enter for newline."
            " Required fields marked with *[/]\n"
        )

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
    """Prompt for multiline text using prompt_toolkit."""
    default_text = str(prev) if prev else ""

    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    session = PromptSession(key_bindings=kb)
    console.print(f"[cyan]{label}[/]")
    result = session.prompt("> ", default=default_text, multiline=True)
    return result.strip() if result else None


def _ask_enum(label: str, field: FieldDefinition, prev: PayloadValue | None = None) -> str | None:
    """Prompt for an enum value."""
    enum_values = field.enum_values or ()
    choices = list(enum_values)
    if not field.required:
        choices = ["(skip)"] + choices

    completer = WordCompleter(choices, ignore_case=True)
    default = str(prev) if prev and str(prev) in enum_values else choices[0]
    session = PromptSession()
    choices_str = "/".join(choices)
    selected = (
        session.prompt(f"{label} [{choices_str}]: ", completer=completer).strip() or default
    )

    if selected == "(skip)":
        return None
    return selected


def _ask_int_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> int | None:
    """Prompt for an int value."""
    default = str(int(prev)) if isinstance(prev, (int, float)) else ""
    session = PromptSession()
    raw = session.prompt(f"{label}: ", default=default).strip()
    if not raw:
        return None
    return cast(int, coerce_value(field, raw))


def _ask_float_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> float | None:
    """Prompt for a float value."""
    default = str(float(prev)) if isinstance(prev, (int, float)) else ""
    session = PromptSession()
    raw = session.prompt(f"{label}: ", default=default).strip()
    if not raw:
        return None
    return cast(float, coerce_value(field, raw))


def _ask_bool_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> bool | None:
    """Prompt for a bool value."""
    session = PromptSession()
    if field.required:
        default = "y" if prev else "n"
        ans = session.prompt(f"{label} [y/n]: ", default=default).strip().lower()
        return ans in ("y", "yes")

    choices = ["yes", "no", "(skip)"]
    default = "yes" if prev else "(skip)"
    completer = WordCompleter(choices, ignore_case=True)
    selected = session.prompt(
        f"{label} [yes/no/(skip)]: ", completer=completer, default=default
    ).strip() or default

    if selected == "(skip)":
        return None
    return cast(bool, coerce_value(field, selected))


def _ask_date_field(
    label: str, field: FieldDefinition, prev: PayloadValue | None = None
) -> date | None:
    """Prompt for a date value (YYYY-MM-DD)."""
    default = prev.isoformat() if isinstance(prev, date) else ""
    session = PromptSession()
    raw = session.prompt(f"{label} (YYYY-MM-DD): ", default=default).strip()
    if not raw:
        return None
    return cast(date, coerce_value(field, raw))


def _ask_array_field(label: str, prev: PayloadValue | None = None) -> list[str] | None:
    """Prompt for an array<string> value (comma-separated)."""
    default = ", ".join(prev) if isinstance(prev, list) else ""
    session = PromptSession()
    raw = session.prompt(f"{label} (comma-separated): ", default=default).strip()
    if not raw:
        return None
    return cast(
        list[str],
        coerce_value(FieldDefinition(name="temp", type=FieldType.ARRAY_STRING), raw),
    )
