from __future__ import annotations

import typer
from rich.console import Console

from specdd.commands._common import require_project_root
from specdd.paths import get_logs_dir

console = Console()
app = typer.Typer(help="Log viewing")


@app.command("tail")
def logs_tail(
    n: int = typer.Option(50, "-n", help="Number of lines to show"),
) -> None:
    """Tail the runtime log."""
    root = require_project_root()
    log_file = get_logs_dir(root) / "runtime.log"

    if not log_file.exists():
        console.print("[dim]No runtime log yet.[/dim]")
        return

    lines = log_file.read_text(encoding="utf-8").splitlines()
    for line in lines[-n:]:
        console.print(line)


@app.command("show")
def logs_show(
    task_id: int = typer.Argument(..., help="Task ID"),
) -> None:
    """Show all log entries for a task (runtime + test logs)."""
    root = require_project_root()
    logs_dir = get_logs_dir(root)

    # Filter runtime.log for task_id
    runtime_log = logs_dir / "runtime.log"
    if runtime_log.exists():
        import json as _json
        console.print(f"[bold]Runtime log entries for task {task_id}:[/bold]")
        found = False
        for line in runtime_log.read_text(encoding="utf-8").splitlines():
            try:
                entry = _json.loads(line)
                if str(entry.get("task_id", "")) == str(task_id):
                    console.print(line)
                    found = True
            except Exception:
                pass
        if not found:
            console.print("  (none)")

    # Show test logs
    tests_dir = logs_dir / "tests"
    if tests_dir.exists():
        test_logs = sorted(tests_dir.glob(f"{task_id}-*.log"))
        if test_logs:
            console.print(f"\n[bold]Test logs for task {task_id}:[/bold]")
            for tl in test_logs:
                console.print(f"\n--- {tl.name} ---")
                console.print(tl.read_text(encoding="utf-8"))
        else:
            console.print(f"\n[dim]No test logs for task {task_id}.[/dim]")
