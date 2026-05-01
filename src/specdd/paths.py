from pathlib import Path


def validate_path_under(path: str, allowed_subdir: str, project_root: str) -> Path:
    """
    Return the resolved absolute Path if valid. Raise ValueError if the path
    resolves outside project_root/allowed_subdir (handles '..', symlinks,
    absolute paths outside project).
    """
    project = Path(project_root).resolve()
    allowed = (project / allowed_subdir).resolve()

    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (project / path).resolve()

    # Containment check — works even if resolved doesn't exist yet
    try:
        resolved.relative_to(allowed)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved}' which is outside allowed root '{allowed}'"
        )

    return resolved


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start (default CWD) looking for .specdd/."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / ".specdd").is_dir():
            return directory
    return None


def get_db_path(project_root: Path) -> Path:
    return project_root / ".specdd" / "state.db"


def get_logs_dir(project_root: Path) -> Path:
    return project_root / ".specdd" / "logs"


def get_config_path(project_root: Path) -> Path:
    return project_root / ".specdd" / "config.yml"
