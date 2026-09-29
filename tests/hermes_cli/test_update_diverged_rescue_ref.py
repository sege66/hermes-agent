"""`hermes update` must not drop local commits without leaving a named way back.

The fork merges same-branch divergence when it shares an ancestor with upstream,
preserving both histories and files. Orphan history still resets only after
parking the old HEAD under ``refs/hermes-update-backups/`` and printing its name.
The installer update paths are covered in
``tests/scripts/install/test_install_diverged_rescue_ref.py``.
"""

from __future__ import annotations

import subprocess

import pytest

from hermes_cli import update_cmd


GIT = ["git"]


def _git(repo, *args, check=True):
    return subprocess.run(
        GIT + list(args), cwd=repo, capture_output=True, text=True, check=check)


def _commit(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def diverged_checkout(tmp_path):
    """A checkout on ``main`` carrying a local commit its ``origin/main`` does not have."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, "shared.txt", "shared\n")
    _commit(upstream, "upstream-only.txt", "upstream\n")

    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", str(upstream), str(checkout))
    _git(checkout, "reset", "-q", "--hard", "HEAD~1")          # back to the shared commit
    local_sha = _commit(checkout, "local-fix.txt", "local\n")  # diverges from origin/main
    return checkout, local_sha


def _rescue_refs(checkout):
    out = _git(checkout, "for-each-ref", "--format=%(refname) %(objectname)",
               "refs/hermes-update-backups/").stdout
    return dict(line.split() for line in out.splitlines() if line.strip())


def _assert_reset_kept_local_commit(checkout, local_sha, output):
    head = _git(checkout, "rev-parse", "HEAD").stdout.strip()
    origin = _git(checkout, "rev-parse", "origin/main").stdout.strip()
    assert head == origin, "the reset itself must still happen"
    refs = [ref for ref, sha in _rescue_refs(checkout).items() if sha == local_sha]
    assert len(refs) == 1, f"the dropped commit needs exactly one rescue ref: {_rescue_refs(checkout)}"
    assert refs[0].startswith("refs/hermes-update-backups/orphan-main-")
    assert refs[0] in output, "the user must be told where the commits went"
    dropped = _git(checkout, "log", "--format=%H", f"origin/main..{refs[0]}").stdout.split()
    assert dropped == [local_sha]


def test_hermes_update_keeps_local_commit_behind_a_rescue_ref(
        diverged_checkout, monkeypatch, capsys):
    """The real apply path preserves local and upstream ancestry and files."""
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
    assert "1 unique commit(s) ahead of origin/main" in out
    assert "merging to preserve them" in out
    assert "resetting" not in out


def test_orphan_history_resets_with_named_rescue_ref(diverged_checkout, monkeypatch, capsys):
    checkout, _ = diverged_checkout
    _git(checkout, "checkout", "--orphan", "orphan")
    _git(checkout, "branch", "-D", "main")
    _git(checkout, "branch", "-m", "main")
    local_sha = _commit(checkout, "orphan-only.txt", "orphan\n")
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)

    update_cmd._pull_updates(
        GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
        discard_local_changes=False, keep_stash=False)

    _assert_reset_kept_local_commit(checkout, local_sha, capsys.readouterr().out)
    assert _git(checkout, "show", f"{local_sha}:orphan-only.txt").stdout == "orphan\n"
    assert (checkout / "upstream-only.txt").read_text(encoding="utf-8") == "upstream\n"


@pytest.fixture()
def fast_forward_checkout(tmp_path):
    """A checkout whose HEAD is strictly behind origin/main."""
    upstream = tmp_path / "linear-upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    first = _commit(upstream, "shared.txt", "shared\n")
    _commit(upstream, "upstream-only.txt", "upstream\n")

    checkout = tmp_path / "linear-checkout"
    _git(tmp_path, "clone", "-q", str(upstream), str(checkout))
    _git(checkout, "reset", "-q", "--hard", first)
    return checkout, first


def test_live_index_lock_is_reported_without_false_divergence(
        fast_forward_checkout, monkeypatch, capsys):
    checkout, before = fast_forward_checkout
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)
    (checkout / ".git" / "index.lock").touch()

    with pytest.raises(SystemExit) as exc:
        update_cmd._pull_updates(
            GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
            discard_local_changes=False, keep_stash=False)

    assert exc.value.code == 1
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == before
    assert _rescue_refs(checkout) == {}
    out = capsys.readouterr().out
    assert "index.lock" in out
    assert "HEAD is still an ancestor of origin/main" in out
    assert "Local history has diverged" not in out
    assert "Fast-forward not possible (history diverged)" not in out
    assert "git reset --hard" not in out


def test_operational_ff_failure_preserves_git_error_without_reset(
        fast_forward_checkout, monkeypatch, capsys):
    checkout, before = fast_forward_checkout
    monkeypatch.setattr(update_cmd._m(), "PROJECT_ROOT", checkout)
    real_git_run = update_cmd._git_run

    def fail_merge(git_cmd, args, *rest, **kwargs):
        if args[:2] == ["merge", "--ff-only"]:
            return subprocess.CompletedProcess(
                git_cmd + args, 128, stdout="",
                stderr="fatal: unable to read tree: RPC failed; transfer closed")
        return real_git_run(git_cmd, args, *rest, **kwargs)

    monkeypatch.setattr(update_cmd, "_git_run", fail_merge)

    with pytest.raises(SystemExit) as exc:
        update_cmd._pull_updates(
            GIT, "main", None, prompt_for_restore=False, gw_input_fn=None,
            discard_local_changes=False, keep_stash=False)

    assert exc.value.code == 1
    assert _git(checkout, "rev-parse", "HEAD").stdout.strip() == before
    assert _rescue_refs(checkout) == {}
    out = capsys.readouterr().out
    assert "RPC failed; transfer closed" in out
    assert "HEAD is still an ancestor of origin/main" in out
    assert "Local history has diverged" not in out
    assert "git reset --hard" not in out
