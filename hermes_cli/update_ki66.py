"""Local (ki66) update behaviour, kept out of the upstream-owned update modules.

On this install an external coordinator (``$HERMES_HOME/bin/hermes-update-coordinator``)
owns updates. Upstream files keep only an import and a call per hook:

* ``hermes_cli/main.py``          -> :func:`delegate_update_to_external_coordinator`
* ``hermes_cli/update_cmd.py``    -> :func:`merge_unique_local_commits`,
                                     :func:`complete_protected_update`
* ``hermes_cli/source_check.py``  -> :func:`protected_owner_already_integrated`

``hermes_cli.update_cmd`` is imported lazily and its helpers are read as attributes at call
time, so tests that monkeypatch ``update_cmd`` keep working and no import cycle exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def delegate_update_to_external_coordinator() -> bool:
    """Exec the external coordinator for a real ``hermes update`` command."""
    if os.environ.get("HERMES_UPDATE_COORDINATOR_ACTIVE") == "1":
        return False
    try:
        update_index = sys.argv.index("update")
    except ValueError:
        return False

    passthrough = sys.argv[update_index + 1 :]
    if any(flag in passthrough for flag in ("--plan", "--check")):
        return False

    hermes_home = Path(
        os.environ.get("HERMES_HOME") or Path.home() / ".hermes"
    ).expanduser()
    coordinator = hermes_home / "bin" / "hermes-update-coordinator"
    if not coordinator.is_file() or not os.access(coordinator, os.X_OK):
        return False

    command = [str(coordinator), "update", "--source", "hermes-cli", "--", *passthrough]
    try:
        os.execve(str(coordinator), command, os.environ.copy())
    except OSError as exc:
        print(f"✗ Failed to start the external Hermes update coordinator: {exc}")
        raise SystemExit(1) from exc
    return True


def merge_unique_local_commits(git_cmd, merge_ref: str, has_common_ancestor: bool) -> bool:
    """``_reconcile_diverged_checkout`` hook: merge same-branch divergence instead of resetting.

    Upstream parks the old tip behind a rescue ref and resets whenever the checkout sits on the
    update branch. This fork carries unique local commits on that branch, so history that shares
    an ancestor with the target is merged (both histories survive); only orphaned history falls
    through to upstream's rescue-ref + reset. Returns True when the merge handled the divergence;
    ``sys.exit(1)`` on a merge conflict.
    """
    from hermes_cli import update_cmd as u

    local_ahead = u._count_commits_between(git_cmd, u._m().PROJECT_ROOT, merge_ref, "HEAD")
    if not (has_common_ancestor and local_ahead > 0):
        return False
    print(f"  ⚠ Local HEAD is {local_ahead} unique commit(s) ahead of {merge_ref} — merging to preserve them...")
    u._git_run(git_cmd, ["tag", f"pre-update-{u._time.strftime('%Y%m%d-%H%M%S')}"])
    if u._git_run(git_cmd, ["merge", "--no-edit", merge_ref]).returncode != 0:
        u._git_run(git_cmd, ["merge", "--abort"])
        print("✗ Merge conflict between local commits and upstream — update stopped.")
        print(f"  Resolve manually: cd {u._m().PROJECT_ROOT} && git merge {merge_ref}")
        sys.exit(1)
    return True


def complete_protected_update(git_cmd, use_zip_update, completion_request: dict, windows_gateway_resume) -> bool:
    """``_cmd_update_impl`` hook: finish an update the coordinator already merged and verified.

    The protected worker exports ``HERMES_PROTECTED_UPDATE_HEAD`` for its inner ``hermes update``.
    A second remote selection could install code that never passed its preflight, so only the
    completion runs, and only for exactly that HEAD. Returns False when the env var is unset
    (ordinary update), True after completing; ``sys.exit(1)`` when the checkout does not match.
    """
    protected_head = os.environ.get("HERMES_PROTECTED_UPDATE_HEAD")
    if not protected_head:
        return False
    from hermes_cli import update_cmd as u

    if (os.environ.get("HERMES_UPDATE_COORDINATOR_ACTIVE") != "1"
            or use_zip_update
            or u._capture_head_sha(git_cmd, u._m().PROJECT_ROOT) != protected_head):
        print("✗ Protected update target does not match this checkout. No completion was applied.")
        u._m()._resume_windows_gateways_after_update(windows_gateway_resume)
        sys.exit(1)
    completion_request["expected_sha"] = protected_head
    completion_request["branch"] = u._git_run(git_cmd, ["branch", "--show-current"]).stdout.strip()
    u._complete_source_update(completion_request)
    return True


def protected_owner_already_integrated(result: dict, checkout_root: Path, home: Path) -> bool:
    """``_hold_refused_release`` hook for the coordinator-owned canonical checkout.

    The protected owner merges releases; an ancestor is already installed, never a rollback.
    Rewrites *result* and returns True in that case.
    """
    coordinator = home / "bin" / "hermes-update-coordinator"
    if (result.get("rollback") and checkout_root == (home / "hermes-agent").resolve()
            and coordinator.is_file() and os.access(coordinator, os.X_OK)):
        result.update(updateAvailable=False, behind=0, rollback=False, aheadOfRelease=True)
        return True
    return False
