from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.config import load_config

console = Console()

app = typer.Typer()


def status_command(json_output: bool = False) -> None:
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        summary = queries.get_status_summary(conn)
        pending_plans = queries.list_pending_plans(conn)
        open_escalations = queries.list_open_escalations(conn)

    try:
        cfg = load_config(root)
        project_name = root.name
    except Exception:
        project_name = root.name

    if json_output:
        print_json({
            "project": project_name,
            "tasks_by_status": summary,
            "pending_plans": len(pending_plans),
            "open_escalations": len(open_escalations),
        })
        return

    console.print(f"\n[bold]SpecDD Status:[/bold] {project_name}\n")

    statuses = ["TODO", "PLANNING", "AWAITING_APPROVAL", "IN_PROGRESS", "REVIEW", "DONE", "ESCALATED", "REJECTED"]
    table = Table(title="Tasks", show_header=True)
    table.add_column("Status", style="cyan")
    table.add_column("Count", justify="right")
    for s in statuses:
        count = summary.get(s, 0)
        if count > 0:
            table.add_row(s, str(count))

    console.print(table)
    console.print(f"\nPending plans:    [yellow]{len(pending_plans)}[/yellow]")
    console.print(f"Open escalations: [red]{len(open_escalations)}[/red]\n")
