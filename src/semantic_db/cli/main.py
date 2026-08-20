from typing import Annotated

import typer

from semantic_db import __version__
from semantic_db.cli.commands.collection import collection_app
from semantic_db.cli.commands.record import record_app
from semantic_db.cli.commands.search import search_app
from semantic_db.cli.runner import console

app = typer.Typer(
    no_args_is_help=True,
    help="Semantic search over user-defined structured records.",
)
app.add_typer(collection_app, name="collection")
app.add_typer(record_app, name="record")
app.add_typer(search_app, name="search")


def _version(value: bool) -> None:
    if value:
        console.print(f"semantic-db {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    pass


if __name__ == "__main__":
    app()
