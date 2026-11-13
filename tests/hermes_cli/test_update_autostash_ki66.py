"""Local (ki66) cases split out of the upstream-owned test_update_autostash.py.

Same-branch divergence with a common ancestor merges instead of resetting
(``hermes_cli.update_ki66.merge_unique_local_commits``). The upstream module drops its
``ordinary`` parameters for the same reason: they assert the reset this fork replaces.
"""

from hermes_cli import main as hermes_main, update_cmd
from tests.hermes_cli.test_update_target_identity import git, update_tree  # noqa: F401  (shared fixture)


def test_same_branch_local_commits_merge_without_reset(update_tree, monkeypatch):  # noqa: F811
    t = update_tree
    git(t.clone, 'checkout', '-q', 'main')
    (t.clone / 'local.txt').write_text('local commit\n', encoding='utf-8')
    git(t.clone, 'add', 'local.txt')
    git(t.clone, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'local history')
    before = git(t.clone, 'rev-parse', 'HEAD')
    git(t.clone, 'fetch', '-q', 'origin', 'main')
    monkeypatch.setattr(hermes_main, 'PROJECT_ROOT', t.clone)

    update_cmd._reconcile_diverged_checkout(['git'], 'main', before)

    assert (t.clone / 'local.txt').read_text(encoding='utf-8') == 'local commit\n'
    assert git(t.clone, 'merge-base', '--is-ancestor', before, 'HEAD') == ''
    assert git(t.clone, 'merge-base', '--is-ancestor', t.newer, 'HEAD') == ''
    assert not git(t.clone, 'for-each-ref', '--format=%(refname)', 'refs/hermes-update-backups/')
