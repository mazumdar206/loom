from __future__ import annotations

import json
import sys

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, require_db, print_json
from specdd.db.connection import db_connection
from specdd.db import queries

console = Console()


def validate_specs_command(json_output: bool = False) -> None:
    """
    Sanity-check all task references. Exit 0 if clean, 1 if problems found.
    Checks: spec_refs files exist, bdd_feature_path exists.
    """
    root = require_project_root()
    db = require_db(root)

    with db_connection(db) as conn:
        tasks = queries.list_tasks(conn)

    problems: list[dict] = []

    for task in tasks:
        task_id = task["id"]
        title = task["title"]

        # Check spec_refs
        spec_refs_raw = task.get("spec_refs")
        if spec_refs_raw:
            try:
                refs = json.loads(spec_refs_raw) if isinstance(spec_refs_raw, str) else spec_refs_raw
            except (json.JSONDecodeError, TypeError):
                refs = []
            for ref in refs:
                ref_path = root / ref
                if not ref_path.exists():
                    problems.append({
                        "task_id": task_id,
                        "task_title": title,
                        "type": "missing_spec_ref",
                        "path": ref,
                    })

        # Check bdd_feature_path
        feature = task.get("bdd_feature_path")
        if feature:
            feat_path = root / feature
            if not feat_path.exists():
                problems.append({
                    "task_id": task_id,
                    "task_title": title,
                    "type": "missing_feature_file",
                    "path": feature,
                })

    if json_output:
        print_json({"problems": problems, "count": len(problems), "ok": len(problems) == 0})
        raise typer.Exit(0 if not problems else 1)

    if not problems:
        console.print("[green]✓[/green] All spec references valid.")
        raise typer.Exit(0)

    console.print(f"[red]✗[/red] Found {len(problems)} problem(s):\n")
    for p in problems:
        console.print(f"  Task #{p['task_id']} ({p['task_title']}): {p['type']} — {p['path']}")
    raise typer.Exit(1)
