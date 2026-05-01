from __future__ import annotations

import shutil
import subprocess
import sys

import typer
from rich.console import Console

from specdd.commands._common import require_project_root, print_json
from specdd.db.connection import db_connection
from specdd.db.migrations import get_schema_version
from specdd.paths import get_db_path, get_config_path
from specdd.version import SCHEMA_VERSION, TEMPLATE_VERSION

console = Console()


def doctor_command(json_output: bool = False) -> None:
    """
    Check project health.
    Exit 0: all checks pass.
    Exit 1: blocking issues (project will not function).
    Exit 2: warnings only.
    """
    root = require_project_root()
    blocking: list[str] = []
    warnings: list[str] = []

    # --- Blocking checks ---

    # 1. DB schema version
    db_path = get_db_path(root)
    if not db_path.exists():
        blocking.append("Database not found. Run 'specdd init'.")
    else:
        with db_connection(db_path) as conn:
            ver = get_schema_version(conn)
        if ver != SCHEMA_VERSION:
            blocking.append(f"DB schema version {ver} != package version {SCHEMA_VERSION}. Run 'specdd upgrade'.")

    # 2. MCP binaries on PATH
    for binary in ("specdd-architect-mcp", "specdd-implementer-mcp"):
        if not shutil.which(binary):
            blocking.append(f"Binary '{binary}' not found on PATH.")

    # 3. Settings files exist
    claude_settings = root / ".claude" / "settings.json"
    gemini_settings = root / ".gemini" / "settings.json"
    if not claude_settings.exists():
        blocking.append(f".claude/settings.json not found.")
    if not gemini_settings.exists():
        blocking.append(f".gemini/settings.json not found.")

    # 4. Config parses
    config_path = get_config_path(root)
    config = None
    if not config_path.exists():
        blocking.append(".specdd/config.yml not found.")
    else:
        try:
            from specdd.config import load_config
            config = load_config(root)
        except Exception as exc:
            blocking.append(f".specdd/config.yml invalid: {exc}")

    # 5. Git repository
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=root,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            blocking.append("Project root is not a git repository.")
    except Exception:
        blocking.append("Could not check git repository status.")

    # --- Warning checks ---

    if config:
        # Template version drift
        if config.template_version != TEMPLATE_VERSION:
            warnings.append(
                f"Template version in config ({config.template_version}) differs from package ({TEMPLATE_VERSION}). Run 'specdd upgrade'."
            )

        # Test runners on PATH
        bdd_cmd = config.test_runners.bdd.split()[0]
        if not shutil.which(bdd_cmd):
            warnings.append(f"BDD test runner '{bdd_cmd}' not found on PATH.")
        unit_cmd = config.test_runners.unit.split()[0]
        if not shutil.which(unit_cmd):
            warnings.append(f"Unit test runner '{unit_cmd}' not found on PATH.")

    # Tasks referencing missing spec files
    if db_path.exists():
        import json as _json
        with db_connection(db_path) as conn:
            from specdd.db import queries
            tasks = queries.list_tasks(conn)
        for task in tasks:
            spec_refs_raw = task.get("spec_refs")
            if spec_refs_raw:
                try:
                    refs = _json.loads(spec_refs_raw)
                except Exception:
                    refs = []
                for ref in refs:
                    if not (root / ref).exists():
                        warnings.append(f"Task #{task['id']} references missing spec: {ref}")

    # ADR numbering gaps
    adrs_dir = root / "docs" / "specs" / "adrs"
    if adrs_dir.exists():
        import re
        nums = []
        for f in adrs_dir.glob("*.md"):
            m = re.match(r"^(\d+)-", f.name)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            nums.sort()
            for i in range(len(nums) - 1):
                if nums[i + 1] - nums[i] > 1:
                    warnings.append(f"ADR numbering gap between {nums[i]} and {nums[i+1]}.")

    # --- Report ---
    all_checks = {
        "blocking": blocking,
        "warnings": warnings,
        "healthy": len(blocking) == 0 and len(warnings) == 0,
    }

    if json_output:
        print_json(all_checks)

    else:
        if not blocking and not warnings:
            console.print("[green]✓[/green] All checks passed. Project is healthy.")
        if blocking:
            console.print("[bold red]Blocking issues:[/bold red]")
            for b in blocking:
                console.print(f"  [red]✗[/red] {b}")
        if warnings:
            console.print("[bold yellow]Warnings:[/bold yellow]")
            for w in warnings:
                console.print(f"  [yellow]![/yellow] {w}")

    if blocking:
        raise typer.Exit(1)
    if warnings:
        raise typer.Exit(2)
    raise typer.Exit(0)
