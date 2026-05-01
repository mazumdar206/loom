from __future__ import annotations

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries
from specdd.mcp.core import transition_task
from specdd.mcp.architect import _atomic_write
from specdd.paths import validate_path_under
from specdd.config import load_config

console = Console()


def resolve_command(task_id: int, json_output: bool = False) -> None:
    """Interactively resolve an escalation: apply / modify / reject."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        task = queries.get_task(conn, task_id)
        if not task:
            typer.echo(f"Error: Task {task_id} not found.", err=True)
            raise typer.Exit(1)
        escalation = queries.get_open_escalation(conn, task_id)

    if not escalation:
        typer.echo(f"Error: No open escalation for task {task_id}.", err=True)
        raise typer.Exit(1)

    if task["status"] != "ESCALATED":
        typer.echo(f"Error: Task {task_id} is not ESCALATED (current: {task['status']}).", err=True)
        raise typer.Exit(1)

    console.print(f"\n[bold]Escalation for Task #{task_id}:[/bold] {task['title']}\n")
    console.print(f"[bold]Conflict:[/bold]\n{escalation['conflict']}\n")
    console.print(f"[bold]Proposed amendment:[/bold]\n{escalation['proposed_amendment']}\n")

    action = typer.prompt("Action [apply/modify/reject]").strip().lower()
    if action not in ("apply", "modify", "reject"):
        typer.echo("Error: Invalid action. Must be apply, modify, or reject.", err=True)
        raise typer.Exit(1)

    resolution_notes = typer.prompt("Resolution notes")

    if action in ("apply", "modify"):
        spec_path = typer.prompt("Spec path to write (relative to project root)")
        if action == "apply":
            spec_content = escalation["proposed_amendment"]
            console.print("[dim]Using proposed amendment as spec content.[/dim]")
        else:
            console.print("Enter new spec content (end with a line containing only '---END---'):")
            lines = []
            while True:
                line = input()
                if line == "---END---":
                    break
                lines.append(line)
            spec_content = "\n".join(lines)

        try:
            cfg = load_config(root)
            resolved = validate_path_under(spec_path, cfg.paths.specs, str(root))
        except (ValueError, FileNotFoundError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1)

        _atomic_write(resolved, spec_content)

        with db_connection(db) as conn:
            queries.resolve_escalation(conn, escalation["id"], "RESOLVED", resolution_notes)

        transitioned = transition_task(db, task_id, "ESCALATED", "TODO", "human",
                                       payload={"action": action, "spec": spec_path})
        if not transitioned:
            typer.echo("Error: Task state changed concurrently.", err=True)
            raise typer.Exit(1)

        if json_output:
            print_json({"task_id": task_id, "status": "TODO", "spec_updated": spec_path})
        else:
            console.print(f"\n[green]✓[/green] Escalation resolved. Task #{task_id} re-queued as TODO.")
            console.print("  Run: ./run-implementer.sh")

    else:  # reject
        with db_connection(db) as conn:
            queries.resolve_escalation(conn, escalation["id"], "REJECTED", resolution_notes)

        transitioned = transition_task(db, task_id, "ESCALATED", "REJECTED", "human",
                                       payload={"action": "reject"})
        if not transitioned:
            typer.echo("Error: Task state changed concurrently.", err=True)
            raise typer.Exit(1)

        if json_output:
            print_json({"task_id": task_id, "status": "REJECTED"})
        else:
            console.print(f"\n[red]✗[/red] Task #{task_id} rejected.")
