"""A real git repository that has released `PREVIOUS`, for the `scripts/release.py` tests.

`PREVIOUS` is committed and tagged (annotated), then a later commit moves the marketplace
pointer to that tag by `ref` and `sha` and adds unreleased work: what `main` looks like after a
pointer PR. `scripts/release.py prepare NEXT` turns it into a coherent release tree.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from types import ModuleType

PREVIOUS = "1.2.2"
NEXT = "1.3.0"
TODAY = dt.date(2026, 10, 27)
REPO_URL = "https://github.com/briandconnelly/amicus"
PIN = "git+https://github.com/briandconnelly/amicus.git@v{}"

UNRELEASED_BODY = """### Added

- A new thing.

### Fixed

- A broken thing.
"""

# Formatted the way no JSON serializer would write it, so any rewrite of the file shows.
MARKETPLACE = """{"name": "amicus",   "owner": {"name": "someone"},
  "plugins": [ {"name": "amicus", "description": "a plugin",
    "source": {"source": "url", "url": "https://github.com/briandconnelly/amicus.git",
               "ref": "v%s", "sha": "%s"} } ]}"""


def changelog(unreleased: str) -> str:
    return f"""# Changelog

Some lead text.

## [Unreleased]
{unreleased}
## [{PREVIOUS}] - 2026-09-01

### Added

- An earlier thing.

[Unreleased]: {REPO_URL}/compare/v{PREVIOUS}...HEAD
[{PREVIOUS}]: {REPO_URL}/releases/tag/v{PREVIOUS}
"""


def readme(version: str) -> str:
    return f"""# amicus

```json
{{"args": ["--from", "{PIN.format(version)}", "amicus-mcp"]}}
```

## Status and known limits

{PREVIOUS} is the current release.
"""


def manifest(version: str) -> str:
    return f'{{\n  "name": "amicus",\n  "version": "{version}",\n  "skills": "./skills/"\n}}\n'


def mcp(version: str) -> str:
    return json.dumps(
        {"mcpServers": {"amicus": {"command": "uvx", "args": ["--from", PIN.format(version)]}}},
        indent=2,
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_released_repo(repo: Path, release: ModuleType) -> None:
    """Fill the empty directory `repo` as above, on `main`; `release` is the loaded script."""
    release_state = release.release_state
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(
        repo,
        "pyproject.toml",
        f'[project]\nname = "amicus"\nversion = "{PREVIOUS}"\n\n'
        '[tool.ruff]\ntarget-version = "py311"\n',
    )
    write(repo, "src/amicus/__init__.py", f'"""amicus."""\n\n__version__ = "{PREVIOUS}"\n')
    for path in release.PLUGIN_MANIFESTS:
        write(repo, path, manifest(PREVIOUS))
    write(repo, ".mcp.json", mcp(PREVIOUS))
    write(repo, "README.md", readme(PREVIOUS))
    write(repo, "CHANGELOG.md", changelog("\n"))
    write(repo, release.MARKETPLACE_PATH, MARKETPLACE % ("0.0.1", "0" * 40))
    write(repo, release_state.DEPRECATIONS_PATH, "DEPRECATED_TOOLS: dict = {}\n")
    write(repo, release_state.LEGACY_ENV_SPEC_PATH, 'LEGACY_REMOVAL_VERSION = "9.0.0"\n')
    write(repo, release_state.GLOBAL_ENV_PATH, "")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"release {PREVIOUS}")
    git(repo, "tag", "-a", f"v{PREVIOUS}", "-m", "evidence")
    released = git(repo, "rev-parse", "HEAD")

    write(repo, release.MARKETPLACE_PATH, MARKETPLACE % (PREVIOUS, released))
    write(repo, "CHANGELOG.md", changelog("\n" + UNRELEASED_BODY))
    git(repo, "commit", "-q", "-am", "work after the release")
