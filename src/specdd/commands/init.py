"""specdd init — bootstrap a project into SpecDD-ready state."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path

import jinja2
import typer
from rich.console import Console

from specdd.db.connection import db_connection
from specdd.db.migrations import initialize_db
from specdd.paths import get_db_path, get_logs_dir
from specdd.version import TEMPLATE_VERSION

console = Console()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _render(template_name: str, context: dict) -> str:
    loader = jinja2.FileSystemLoader(str(_TEMPLATES_DIR))
    env = jinja2.Environment(loader=loader, autoescape=False)
    tmpl = env.get_template(template_name)
    return tmpl.render(**context)


def _safe_write(path: Path, content: str, force: bool) -> bool:
    """Write file; if it exists, prompt unless force. Returns True if written."""
    if path.exists() and not force:
        overwrite = typer.confirm(f"  {path.relative_to(path.parent.parent)} already exists. Overwrite?", default=False)
        if not overwrite:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def init_command(force: bool = False) -> None:
    """Bootstrap project into SpecDD-ready state. Idempotent."""
    root = Path.cwd()

    console.print("\n[bold]SpecDD Init[/bold]\n")

    # Detect existing setup
    existing_specdd = (root / ".specdd").exists()
    existing_git = (root / ".git").exists()

    if existing_specdd and not force:
        console.print("[yellow]Note:[/yellow] .specdd/ already exists. Files will prompt before overwriting.")
        console.print("Use --force to overwrite all without prompting.\n")

    # Prompt for project info
    project_name = typer.prompt("Project name", default=root.name)
    architect_model = typer.prompt("Architect model", default="claude-sonnet-4-6")
    implementer_model = typer.prompt("Implementer model", default="gemini-3-flash")
    source_dir = typer.prompt("Source directory", default="src")
    bdd_framework = typer.prompt("BDD framework", default="behave")
    unit_framework = typer.prompt("Unit test framework", default="pytest")

    bash_allowlist = ["pytest *", "behave *", "git diff*", "git status"]

    context = {
        "project_name": project_name,
        "architect_model": architect_model,
        "implementer_model": implementer_model,
        "source_dir": source_dir,
        "bdd_framework": bdd_framework,
        "unit_framework": unit_framework,
        "bash_allowlist": bash_allowlist,
        "template_version": TEMPLATE_VERSION,
        "date": date.today().isoformat(),
        # Absolute path so MCP subprocess launched by Claude Code resolves correctly
        "project_root": str(root.resolve()),
    }

    console.print("\n[bold]Writing files...[/bold]\n")

    # 1. .specdd/config.yml
    config_path = root / ".specdd" / "config.yml"
    config_content = _render("config.yml.j2", context)
    if _safe_write(config_path, config_content, force):
        console.print(f"  [green]✓[/green] .specdd/config.yml")

    # 2. Initialize DB
    db_path = get_db_path(root)
    if not db_path.exists() or force:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with db_connection(db_path) as conn:
            initialize_db(conn)
        console.print(f"  [green]✓[/green] .specdd/state.db (initialized)")
    else:
        console.print(f"  [dim]–[/dim] .specdd/state.db (exists, skipped)")

    # 3. .specdd/logs/
    logs_dir = get_logs_dir(root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"  [green]✓[/green] .specdd/logs/")

    # 4a. .mcp.json — Claude Code reads MCP servers from here (not .claude/settings.json)
    mcp_json = root / ".mcp.json"
    mcp_content = _render("mcp.json.j2", context)
    if _safe_write(mcp_json, mcp_content, force):
        console.print(f"  [green]✓[/green] .mcp.json (Claude Code MCP server)")

    # 4b. .claude/settings.json — permissions only, no mcpServers
    claude_settings = root / ".claude" / "settings.json"
    claude_content = _render("claude-settings.json.j2", context)
    if _safe_write(claude_settings, claude_content, force):
        console.print(f"  [green]✓[/green] .claude/settings.json (permissions)")

    # 5. .gemini/settings.json
    gemini_settings = root / ".gemini" / "settings.json"
    gemini_content = _render("gemini-settings.json.j2", context)
    if _safe_write(gemini_settings, gemini_content, force):
        console.print(f"  [green]✓[/green] .gemini/settings.json")

    # 6. CLAUDE.md
    claude_md = root / "CLAUDE.md"
    claude_md_content = _render("CLAUDE.md.j2", context)
    if _safe_write(claude_md, claude_md_content, force):
        console.print(f"  [green]✓[/green] CLAUDE.md")

    # 7. GEMINI.md
    gemini_md = root / "GEMINI.md"
    gemini_md_content = _render("GEMINI.md.j2", context)
    if _safe_write(gemini_md, gemini_md_content, force):
        console.print(f"  [green]✓[/green] GEMINI.md")

    # 8. run-implementer.sh
    run_sh = root / "run-implementer.sh"
    run_sh_content = _render("run-implementer.sh.j2", context)
    if _safe_write(run_sh, run_sh_content, force):
        run_sh.chmod(0o755)
        console.print(f"  [green]✓[/green] run-implementer.sh (executable)")

    # 9. docs/specs/ structure
    for subdir in ("architecture", "api", "features", "adrs"):
        d = root / "docs" / "specs" / subdir
        d.mkdir(parents=True, exist_ok=True)
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
    console.print(f"  [green]✓[/green] docs/specs/{{architecture,api,features,adrs}}/")

    # 10. ADR 0001
    adr_src = _TEMPLATES_DIR / "docs_specs" / "adrs" / "0001-record-architecture-decisions.md"
    adr_dst = root / "docs" / "specs" / "adrs" / "0001-record-architecture-decisions.md"
    adr_content = jinja2.Template(adr_src.read_text()).render(**context)
    if _safe_write(adr_dst, adr_content, force):
        console.print(f"  [green]✓[/green] docs/specs/adrs/0001-record-architecture-decisions.md")

    # 11. tests/bdd/ and tests/unit/
    for tests_dir in (root / "tests" / "bdd", root / "tests" / "unit"):
        tests_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = tests_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()
    console.print(f"  [green]✓[/green] tests/bdd/ and tests/unit/")

    # 12. .gitignore additions
    gitignore = root / ".gitignore"
    gitignore_additions = _render("gitignore.j2", context).strip()
    if not gitignore.exists():
        gitignore.write_text(gitignore_additions + "\n", encoding="utf-8")
        console.print(f"  [green]✓[/green] .gitignore (created)")
    else:
        existing = gitignore.read_text(encoding="utf-8")
        if ".specdd/state.db" not in existing:
            with open(gitignore, "a", encoding="utf-8") as fh:
                fh.write("\n" + gitignore_additions + "\n")
            console.print(f"  [green]✓[/green] .gitignore (updated)")
        else:
            console.print(f"  [dim]–[/dim] .gitignore (already has specdd entries)")

    # Done
    console.print("\n[bold green]SpecDD initialized![/bold green]\n")
    console.print("Next steps:")
    console.print("  1. Review generated files")
    console.print("  2. Commit:      git add . && git commit -m \"Initialize SpecDD\"")
    console.print("  3. Architect:   claude")
    console.print("  4. Implementer: ./run-implementer.sh\n")
