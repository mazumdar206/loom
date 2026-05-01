from __future__ import annotations

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.mcp.core import transition_task

console = Console()


def approve_command(task_id: int, json_output: bool = False) -> None:
    """Approve a pending plan: AWAITING_APPROVAL→IN_PROGRESS."""
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
        if not plan:
            typer.echo(f"Error: No pending plan found for task {task_id}.", err=True)
            raise typer.Exit(1)

        queries.approve_plan(conn, plan["id"])

    transitioned = transition_task(db, task_id, "AWAITING_APPROVAL", "IN_PROGRESS", "human",
                                   payload={"plan_id": plan["id"]})
    if not transitioned:
        typer.echo("Error: Task state changed concurrently. Re-read and retry.", err=True)
        raise typer.Exit(1)

    if json_output:
        print_json({"task_id": task_id, "status": "IN_PROGRESS", "plan_id": plan["id"]})
    else:
        console.print(f"[green]✓[/green] Task #{task_id} approved. Status: IN_PROGRESS.")
        console.print("  Run: ./run-implementer.sh")
