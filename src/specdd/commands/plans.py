from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries

console = Console()
app = typer.Typer(help="Plan management")


@app.command("pending")
def plans_pending(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """List plans awaiting approval."""
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        plans = queries.list_pending_plans(conn)

    if json_output:
        print_json({"plans": plans, "count": len(plans)})
        return

    if not plans:
        console.print("No plans pending approval.")
        return

    for plan in plans:
        console.print(f"\n[bold]Plan for Task #{plan['task_id']}:[/bold] {plan['task_title']} ({plan['complexity']})")
        console.print(f"  Plan ID:   {plan['id']}")
        console.print(f"  Submitted: {plan['created_at']}")
        console.print(f"\n  [bold]Plan:[/bold]\n")
        for line in plan["plan_text"].splitlines():
            console.print(f"    {line}")
        console.print(f"\n  Run: specdd approve {plan['task_id']}")
        console.print(f"   or: specdd reject {plan['task_id']} \"<reason>\"")
