from collections.abc import Mapping

from rich.panel import Panel

from semantic_db.cli.runner import console
from semantic_db.domain.collection import CollectionSchema
from semantic_db.domain.record import PayloadValue
from semantic_db.domain.rendering import render, render_preview


def print_schema_preview(schema: CollectionSchema) -> None:
    """Show the exact shape of the text that will be embedded, before anything is
    written — bad rendering is the hardest retrieval problem to notice later."""
    console.print(Panel(render_preview(schema), title="Preview", title_align="left"))


def print_record_preview(schema: CollectionSchema, payload: Mapping[str, PayloadValue]) -> None:
    console.print(Panel(render(schema, payload), title="Preview", title_align="left"))


def preview_panel(schema: CollectionSchema, payload: Mapping[str, PayloadValue]) -> Panel:
    """Return a Panel with the rendered record."""
    return Panel(render(schema, payload), title="Preview", title_align="left")
