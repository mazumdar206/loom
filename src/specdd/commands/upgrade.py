from __future__ import annotations

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, require_db
from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db, get_schema_version
from specdd.version import SCHEMA_VERSION

console = Console()


def upgrade_command() -> None:
    """Apply DB migrations and note template updates."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        current = get_schema_version(conn)

    if current == SCHEMA_VERSION:
        console.print(f"[green]✓[/green] DB schema already at version {SCHEMA_VERSION}. Nothing to do.")
        return

    console.print(f"Upgrading DB schema from version {current} to {SCHEMA_VERSION}...")
    confirm = typer.confirm("Proceed?")
    if not confirm:
        raise typer.Exit(0)

    with db_connection(db) as conn:
        initialize_db(conn)

    console.print(f"[green]✓[/green] DB upgraded to schema version {SCHEMA_VERSION}.")
    console.print("\nNote: Template files (CLAUDE.md, GEMINI.md, settings) may have changed.")
    console.print("Re-run 'specdd init --force' to regenerate (review diffs before committing).")
