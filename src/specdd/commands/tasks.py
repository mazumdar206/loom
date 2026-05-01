from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries

console = Console()
app = typer.Typer(help="Task management")


@app.command("list")
def tasks_list(
    status: str = typer.Option("", "--status", "-s", help="Filter by status"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List tasks."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        task_list = queries.list_tasks(conn, status or None)

    if json_output:
        print_json({"tasks": task_list, "count": len(task_list)})
        return

    table = Table(title=f"Tasks{' [' + status + ']' if status else ''}", show_header=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Status", style="cyan", width=18)
    table.add_column("Complexity", width=10)
    table.add_column("Pri", justify="right", width=4)
    table.add_column("Title")

    for t in task_list:
        table.add_row(
            str(t["id"]),
            t["status"],
            t["complexity"],
            str(t["priority"]),
            t["title"],
        )
    console.print(table)


@app.command("show")
def tasks_show(
    task_id: int = typer.Argument(..., help="Task ID"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show full task detail with event history."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        task = queries.get_task(conn, task_id)
        if not task:
            typer.echo(f"Error: Task {task_id} not found.", err=True)
            raise typer.Exit(1)
        events = queries.get_task_events(conn, task_id)

    if json_output:
        print_json({"task": task, "events": events})
        return

    console.print(f"\n[bold]Task #{task_id}:[/bold] {task['title']}")
    console.print(f"  Status:     [cyan]{task['status']}[/cyan]")
    console.print(f"  Complexity: {task['complexity']}")
    console.print(f"  Priority:   {task['priority']}")
    if task.get("description"):
        console.print(f"  Description:\n    {task['description']}")
    if task.get("spec_refs"):
        refs = json.loads(task["spec_refs"]) if isinstance(task["spec_refs"], str) else task["spec_refs"]
        console.print(f"  Spec refs:  {', '.join(refs)}")
    if task.get("bdd_feature_path"):
        console.print(f"  Feature:    {task['bdd_feature_path']}")
    if task.get("notes"):
        console.print(f"  Notes:      {task['notes']}")
    console.print(f"  Created:    {task['created_at']}")
    console.print(f"  Updated:    {task['updated_at']}")
    if task.get("completed_at"):
        console.print(f"  Completed:  {task['completed_at']}")

    if events:
        console.print("\n  [bold]Event History:[/bold]")
        for ev in events:
            payload_str = ""
            if ev.get("payload"):
                try:
                    p = json.loads(ev["payload"])
                    payload_str = f" {p}"
                except Exception:
                    payload_str = f" {ev['payload']}"
            console.print(f"    [{ev['created_at']}] {ev['actor']}: {ev['event_type']}{payload_str}")
    console.print()
