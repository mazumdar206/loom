"""Shared helpers for CLI commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from specdd.paths import find_project_root, get_db_path


def require_project_root() -> Path:
    root = find_project_root()
    if root is None:
        typer.echo("Error: No .specdd/ directory found. Run 'specdd init' first.", err=True)
        raise typer.Exit(1)
    return root


def require_db(project_root: Path) -> Path:
    db = get_db_path(project_root)
    if not db.exists():
        typer.echo(f"Error: Database not found at {db}. Run 'specdd init' first.", err=True)
        raise typer.Exit(1)
    return db


def print_json(data) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))
