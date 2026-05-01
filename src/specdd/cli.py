"""Main Typer CLI for specdd."""
from __future__ import annotations

import typer

from specdd.version import __version__

app = typer.Typer(
    help="SpecDD — Spec-Driven Development CLI orchestrator.",
    no_args_is_help=True,
)

# Sub-command groups
tasks_app = typer.Typer(help="Task management commands.")
app.add_typer(tasks_app, name="tasks")

plans_app = typer.Typer(help="Plan management commands.")
app.add_typer(plans_app, name="plans")

logs_app = typer.Typer(help="Log viewing commands.")
app.add_typer(logs_app, name="logs")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"specdd {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(None, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version."),
) -> None:
    pass


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@app.command("init")
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files without prompting."),
) -> None:
    """Bootstrap a project into SpecDD-ready state."""
    from specdd.commands.init import init_command
    init_command(force=force)


@app.command("status")
def status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show one-screen project status summary."""
    from specdd.commands.status import status_command
    status_command(json_output=json_output)


@app.command("approve")
def approve(
    task_id: int = typer.Argument(..., help="Task ID to approve."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Approve a pending plan (AWAITING_APPROVAL → IN_PROGRESS)."""
    from specdd.commands.approve import approve_command
    approve_command(task_id=task_id, json_output=json_output)


@app.command("reject")
def reject(
    task_id: int = typer.Argument(..., help="Task ID to reject."),
    reason: str = typer.Argument(..., help="Rejection reason."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Reject a plan (AWAITING_APPROVAL → REJECTED, terminal)."""
    from specdd.commands.reject import reject_command
    reject_command(task_id=task_id, reason=reason, json_output=json_output)


@app.command("escalations")
def escalations(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List open escalations."""
    from specdd.commands.escalations import escalations_command
    escalations_command(json_output=json_output)


@app.command("resolve")
def resolve(
    task_id: int = typer.Argument(..., help="Task ID with open escalation."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Interactively resolve an escalation."""
    from specdd.commands.resolve import resolve_command
    resolve_command(task_id=task_id, json_output=json_output)


@app.command("validate-specs")
def validate_specs(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Sanity-check all task spec and feature references. Exit 0=clean, 1=problems."""
    from specdd.commands.validate_specs import validate_specs_command
    validate_specs_command(json_output=json_output)


@app.command("doctor")
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Check project health. Exit 0=healthy, 1=blocking, 2=warnings only."""
    from specdd.commands.doctor import doctor_command
    doctor_command(json_output=json_output)


@app.command("upgrade")
def upgrade() -> None:
    """Apply DB migrations and note template updates."""
    from specdd.commands.upgrade import upgrade_command
    upgrade_command()


# ---------------------------------------------------------------------------
# tasks sub-commands
# ---------------------------------------------------------------------------


@tasks_app.command("list")
def tasks_list(
    status: str = typer.Option("", "--status", "-s", help="Filter by status."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List tasks."""
    from specdd.commands.tasks import tasks_list as _tasks_list
    _tasks_list(status=status, json_output=json_output)


@tasks_app.command("show")
def tasks_show(
    task_id: int = typer.Argument(..., help="Task ID."),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show full task detail with event history."""
    from specdd.commands.tasks import tasks_show as _tasks_show
    _tasks_show(task_id=task_id, json_output=json_output)


# ---------------------------------------------------------------------------
# plans sub-commands
# ---------------------------------------------------------------------------


@plans_app.command("pending")
def plans_pending(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List plans awaiting approval."""
    from specdd.commands.plans import plans_pending as _plans_pending
    _plans_pending(json_output=json_output)


# ---------------------------------------------------------------------------
# logs sub-commands
# ---------------------------------------------------------------------------


@logs_app.command("tail")
def logs_tail(
    n: int = typer.Option(50, "-n", help="Number of lines to show."),
) -> None:
    """Tail the runtime log."""
    from specdd.commands.logs import logs_tail as _logs_tail
    _logs_tail(n=n)


@logs_app.command("show")
def logs_show(
    task_id: int = typer.Argument(..., help="Task ID."),
) -> None:
    """Show all log entries for a task."""
    from specdd.commands.logs import logs_show as _logs_show
    _logs_show(task_id=task_id)
