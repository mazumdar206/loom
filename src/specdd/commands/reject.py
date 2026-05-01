from __future__ import annotations

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.mcp.core import transition_task

console = Console()


def reject_command(task_id: int, reason: str, json_output: bool = False) -> None:
    """Reject a plan: plan→REJECTED, task→REJECTED (terminal)."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        task = queries.get_task(conn, task_id)
        if not task:
            typer.echo(f"Error: Task {task_id} not found.", err=True)
            raise typer.Exit(1)

        if task["status"] != "AWAITING_APPROVAL":
            typer.echo(
                f"Error: Task {task_id} is in '{task['status']}', not AWAITING_APPROVAL.",
                err=True,
            )
            raise typer.Exit(1)

        plan = queries.get_pending_plan(conn, task_id)
        if plan:
            queries.reject_plan(conn, plan["id"], reason)

    transitioned = transition_task(db, task_id, "AWAITING_APPROVAL", "REJECTED", "human",
                                   payload={"reason": reason})
    if not transitioned:
        typer.echo("Error: Task state changed concurrently.", err=True)
        raise typer.Exit(1)

    if json_output:
        print_json({"task_id": task_id, "status": "REJECTED", "reason": reason})
    else:
        console.print(f"[red]✗[/red] Task #{task_id} rejected. Status: REJECTED.")
