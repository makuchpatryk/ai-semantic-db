import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import typer
from rich.console import Console

from semantic_db.container import Container, build_container
from semantic_db.domain.errors import SemanticDbError

console = Console()
error_console = Console(stderr=True)

VALIDATION_EXIT_CODE = 2


@contextmanager
def guard() -> Iterator[None]:
    """Same error contract as `run`, for the synchronous parts of a command
    (spec parsing, prompts) that happen before anything is wired."""
    try:
        yield
    except SemanticDbError as exc:
        error_console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(VALIDATION_EXIT_CODE) from exc


def run[T](main: Callable[[Container], Awaitable[T]]) -> T:
    """Bridge Typer's sync commands to the async use cases, and turn every domain
    error into a message plus exit code 2 instead of a traceback."""

    async def _run() -> T:
        async with build_container() as container:
            return await main(container)

    try:
        return asyncio.run(_run())
    except SemanticDbError as exc:
        error_console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(VALIDATION_EXIT_CODE) from exc
