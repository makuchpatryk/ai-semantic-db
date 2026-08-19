import re

from semantic_db.domain.collection import FieldDefinition
from semantic_db.domain.errors import SchemaError
from semantic_db.domain.field_types import FieldType

ENUM_RE = re.compile(r"^enum\((?P<values>.*)\)$")
VALID_FLAGS = ("embed", "required")
VALID_KEYS = ("unit",)

GRAMMAR = "name:type[:flags][:key=value] (e.g. price:float:embed:unit=PLN)"


def parse_field_spec(spec: str) -> FieldDefinition:
    """Parse one `--field` value (PRD 4.2).

    Splitting on ':' is safe because `enum(a|b|c)` never contains a colon.
    """
    segments = spec.split(":")
    if len(segments) < 2 or not segments[0].strip():
        raise SchemaError(f"invalid field spec '{spec}'; expected {GRAMMAR}")

    name = segments[0].strip()
    field_type, enum_values = _parse_type(segments[1].strip(), spec)
    flags, options = _parse_modifiers(segments[2:], spec)

    return FieldDefinition(
        name=name,
        type=field_type,
        embed="embed" in flags,
        required="required" in flags,
        enum_values=enum_values,
        unit=options.get("unit"),
    )


def _parse_type(text: str, spec: str) -> tuple[FieldType, tuple[str, ...] | None]:
    match = ENUM_RE.match(text)
    if match:
        values = tuple(value.strip() for value in match.group("values").split("|") if value.strip())
        if not values:
            raise SchemaError(f"invalid field spec '{spec}'; enum declares no values")
        return FieldType.ENUM, values

    if text == FieldType.ENUM:
        raise SchemaError(
            f"invalid field spec '{spec}'; enum needs its values inline, as enum(a|b|c)"
        )

    try:
        return FieldType(text), None
    except ValueError:
        raise SchemaError(
            f"unknown type '{text}' in field spec '{spec}'; valid types: {', '.join(FieldType)}"
        ) from None


def _parse_modifiers(segments: list[str], spec: str) -> tuple[set[str], dict[str, str]]:
    flags: set[str] = set()
    options: dict[str, str] = {}

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        if "=" in segment:
            key, _, value = segment.partition("=")
            key = key.strip()
            if key not in VALID_KEYS:
                raise SchemaError(
                    f"unknown option '{key}' in field spec '{spec}'; "
                    f"valid options: {', '.join(VALID_KEYS)}"
                )
            options[key] = value.strip()
            continue
        for flag in segment.split(","):
            flag = flag.strip()
            if not flag:
                continue
            if flag not in VALID_FLAGS:
                raise SchemaError(
                    f"unknown flag '{flag}' in field spec '{spec}'; "
                    f"valid flags: {', '.join(VALID_FLAGS)}"
                )
            flags.add(flag)

    return flags, options
