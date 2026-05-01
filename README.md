# specdd

Spec-Driven Development CLI — orchestrates AI-assisted development between Claude (Architect) and Gemini (Implementer).

## Install

```bash
pipx install specdd
```

## Usage

```bash
specdd init          # Bootstrap a project
specdd status        # View project state
specdd tasks list    # List tasks
specdd plans pending # Plans awaiting approval
specdd approve <id>  # Approve a plan
specdd doctor        # Check project health
```

## Development

```bash
uv sync
uv run pytest
```
