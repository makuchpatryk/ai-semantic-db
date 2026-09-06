from collections.abc import Sequence

from rich.table import Table

from semantic_db.domain.collection import CollectionSchema
from semantic_db.domain.record import Record
from semantic_db.domain.rendering import format_value


def record_table(schema: CollectionSchema, records: Sequence[Record]) -> Table:
    """Build a Rich table with ID and all embedded fields."""
    table = Table()
    table.add_column("ID", style="cyan")

    for field in schema.embedded_fields:
        table.add_column(field.label, style="green", no_wrap=True, overflow="ellipsis")

    for record in records:
        row = [str(record.id)]
        for field in schema.embedded_fields:
            value = record.payload.get(field.name)
            formatted = format_value(field, value) if value is not None else ""
            row.append(formatted)
        table.add_row(*row)

    return table
