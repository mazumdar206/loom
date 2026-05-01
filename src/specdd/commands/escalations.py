from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries

console = Console()


def escalations_command(json_output: bool = False) -> None:
    """List open escalations."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        escalations = queries.list_open_escalations(conn)

    if json_output:
        print_json({"escalations": escalations, "count": len(escalations)})
        return

    if not escalations:
        console.print("No open escalations.")
        return

    table = Table(title="Open Escalations", show_header=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Task #", width=7)
    table.add_column("Task Title")
    table.add_column("Created", width=20)

    for esc in escalations:
        table.add_row(
            str(esc["id"]),
            str(esc["task_id"]),
            esc.get("task_title", ""),
            esc["created_at"],
        )
    console.print(table)
    console.print("\nRun: specdd resolve <task-id>")
