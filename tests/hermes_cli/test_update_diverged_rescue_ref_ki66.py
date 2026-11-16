"""Local (ki66) cases split out of the upstream-owned test_update_diverged_rescue_ref.py.

The fork merges same-branch divergence when it shares an ancestor with upstream
(``hermes_cli.update_ki66.merge_unique_local_commits``), preserving both histories and
files. Orphan history still resets only after parking the old HEAD under
``refs/hermes-update-backups/`` and printing its name. The upstream
``test_hermes_update_keeps_local_commit_behind_a_rescue_ref`` asserts the reset this fork
replaces; the repository-root conftest.py deselects it and the merge case below replaces it.
"""

from __future__ import annotations

from hermes_cli import update_cmd
from tests.hermes_cli.test_update_diverged_rescue_ref import (
    GIT,
    _commit,
    _git,
    _rescue_refs,
    diverged_checkout,  # noqa: F401  (shared fixture)
)


def test_orphan_history_resets_with_named_rescue_ref(diverged_checkout, monkeypatch, capsys):  # noqa: F811
    checkout, _ = diverged_checkout
    _git(checkout, "checkout", "--orphan", "orphan")
    _git(checkout, "branch", "-D", "main")
    _git(checkout, "branch", "-m", "main")
    local_sha = _commit(checkout, "orphan-only.txt", "orphan\n")
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)

    update_cmd._pull_updates(
        GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
        discard_local_changes=False, keep_stash=False)

    output = capsys.readouterr().out
    head = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    origin = _git(checkout, "rev-parse", "origin/main").stdout.strip()
    assert head == origin, "the reset itself must still happen"
    refs = [ref for ref, sha in _rescue_refs(checkout).items() if sha == local_sha]
    assert len(refs) == 1, f"the dropped commit needs exactly one rescue ref: {_rescue_refs(checkout)}"
    assert refs[0].startswith("refs/hermes-update-backups/orphan-main-")
    assert refs[0] in output, "the user must be told where the commits went"
    dropped = _git(checkout, "log", "--format=%H", f"origin/main..{refs[0]}").stdout.split()
    assert dropped == [local_sha]
    assert _git(checkout, "show", f"{local_sha}:orphan-only.txt").stdout == "orphan\n"
    assert (checkout / "upstream-only.txt").read_text(encoding="utf-8") == "upstream\n"


def test_same_branch_divergence_merges_and_keeps_both_histories(diverged_checkout, monkeypatch, capsys):  # noqa: F811
    checkout, local_sha = diverged_checkout
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)

    update_cmd._pull_updates(
        GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
        discard_local_changes=False, keep_stash=False)

    out = capsys.readouterr().out
    for tip in (local_sha, "origin/main"):
        assert _git(checkout, "merge-base", "--is-ancestor", tip, "HEAD", check=False).returncode == 0
    assert (checkout / "local-fix.txt").read_text(encoding="utf-8") == "local\n"
    assert (checkout / "upstream-only.txt").read_text(encoding="utf-8") == "upstream\n"
    assert _rescue_refs(checkout) == {}
    tags = _git(checkout, "tag", "--points-at", local_sha).stdout.split()
    assert any(tag.startswith("pre-update-") for tag in tags)
    assert "1 unique commit(s) ahead of" in out
    assert "merging to preserve them" in out
    assert "resetting" not in out
