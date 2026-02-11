# Contributing to renogy-ble

Thanks for contributing.

Start here:

- Read [`AGENTS.md`](AGENTS.md) for repository-specific guardrails.
- Read [`README.md`](README.md) for library purpose, supported devices, and usage.

## Scope and Boundaries

`renogy-ble` is a standalone Python BLE/Modbus library.

- Include protocol, parsing, command framing, and BLE transport changes here.
- Keep this project independent from Home Assistant.
- Do not add Home Assistant entities, lifecycle code, or HA-specific dependencies.

If your change is about Home Assistant behavior, it likely belongs in `renogy-ha`.

## Development Setup

This repository uses `uv` for environment and dependency management.

1. Install dependencies: `uv sync --all-groups`
2. Run tests: `uv run pytest tests`

## Quality Gates

Before opening a PR, run:

1. `uv run ruff format .`
2. `uv run ruff check . --output-format=github`
3. `uv run ty check . --output-format=github`
4. `uv run pytest tests`

## Documentation

- Use Markdown.
- Put project documentation under `docs/`.

## Pull Requests

- Add or update tests for behavior changes.
- Keep changes focused and clearly scoped.
- Use conventional commit prefixes (`fix:`, `feat:`, `docs:`, etc.).
- Do not edit `CHANGELOG.md` or manually update the version (release automation handles it).

## Reporting Issues

When filing a bug, include:

- Device model and BT module (BT-1/BT-2)
- What command/register was read or written
- Minimal reproduction steps
- Logs or raw response bytes when available
