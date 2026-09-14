from semantic_db.domain.errors import SemanticDbError


def parse_set_specs(specs: list[str]) -> dict[str, str]:
    """Parse repeated `--set key=value` values.

    Split on the first '=' only, so `--set "note=a=b"` keeps its value intact.
    """
    values: dict[str, str] = {}
    for spec in specs:
        key, separator, value = spec.partition("=")
        key = key.strip()
        if not separator or not key:
            raise SemanticDbError(f"invalid --set '{spec}'; expected key=value")
        if key in values:
            raise SemanticDbError(f"field '{key}' given twice with --set")
        values[key] = value
    return values


def parse_unset_specs(specs: list[str]) -> frozenset[str]:
    """Parse repeated `--unset key` field names."""
    fields: set[str] = set()
    for spec in specs:
        field = spec.strip()
        if not field:
            raise SemanticDbError(f"invalid --unset '{spec}'; expected a field name")
        if field in fields:
            raise SemanticDbError(f"field '{field}' given twice with --unset")
        fields.add(field)
    return frozenset(fields)
