"""Where a run executes: the workspace itself (DirectSite) or a throwaway worktree seeded
from tracked state (WorktreeSite). The worktree prefix and baseline identity are amicus
policy, shared by every backend and by the JobStore's cleanup guard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.backend.contract import IsolationPolicy
from pontonier.core import redaction, worktree

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from amicus.plugin import BackendPlugin
    from amicus.request import RunSpec

WORKTREE_PREFIX = "amicus-wt-"
WORKTREE_CONFIG = worktree.WorktreeConfig(
    prefix=WORKTREE_PREFIX, identity_name="amicus", identity_email="amicus@local"
)


class SiteError(Exception):
    """A site could not be set up or its diff captured; rendered as an error envelope."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        field: str | None = None,
        repair_alternative: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.field = field
        self.repair_alternative = repair_alternative


class DirectSite:
    def __init__(self, cwd: str) -> None:
        self.cwd = cwd
        self.aliases: tuple[str, ...] = ()
        self.security_warnings: tuple[str, ...] = ()

    def __enter__(self) -> DirectSite:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def capture_diff(self) -> str | None:
        return None


class WorktreeSite:
    def __init__(
        self, repo: str, *, git_timeout: int, on_parent: Callable[[str], None] | None = None
    ) -> None:
        self._repo = repo
        self._timeout = git_timeout
        self._on_parent = on_parent
        self._wt: worktree.Worktree | None = None
        self.cwd = repo
        self.aliases: tuple[str, ...] = ()
        self.security_warnings: tuple[str, ...] = ()

    def __enter__(self) -> WorktreeSite:
        try:
            self._wt = worktree.create(
                self._repo, timeout=self._timeout, on_parent=self._on_parent, config=WORKTREE_CONFIG
            )
        except worktree.NotAGitRepoError as exc:
            raise SiteError(
                "not_a_git_repo", redaction.sanitize_echo_prose(str(exc)), field="workspace_root"
            ) from exc
        except (worktree.NoCommitsError, worktree.WorktreeError) as exc:
            raise SiteError(
                "worktree_error",
                redaction.sanitize_echo_prose(str(exc))[:300],
                repair_alternative="Ensure the repo has at least one commit and a clean git state.",
            ) from exc
        self.cwd = self._wt.path
        self.aliases = worktree.path_aliases(self._wt.path)
        self.security_warnings = (self._wt.baseline_warning,) if self._wt.baseline_warning else ()
        return self

    def __exit__(self, *exc: object) -> bool:
        if self._wt is not None:
            worktree.remove(self._repo, self._wt, timeout=self._timeout)
        return False

    def capture_diff(self) -> str | None:
        assert self._wt is not None
        try:
            return worktree.capture_diff(
                self._wt.path, timeout=self._timeout, config=WORKTREE_CONFIG
            )
        except worktree.WorktreeError as exc:
            raise SiteError(
                "worktree_error", redaction.sanitize_echo_prose(str(exc))[:300]
            ) from exc


def select_site(
    spec: RunSpec, plugin: BackendPlugin, on_parent: Callable[[str], None] | None = None
) -> DirectSite | WorktreeSite:
    if (
        spec.kind == "delegate"
        or plugin.contract.isolation_policy is IsolationPolicy.WORKTREE_ALL_TIERS
    ):
        return WorktreeSite(spec.cwd, git_timeout=spec.git_timeout, on_parent=on_parent)
    return DirectSite(spec.cwd)
