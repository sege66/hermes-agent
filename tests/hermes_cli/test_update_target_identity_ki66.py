"""Local (ki66) cases split out of the upstream-owned test_update_target_identity.py.

Covers ``hermes_cli.update_ki66.complete_protected_update``: the protected worker's inner
``hermes update`` (``HERMES_PROTECTED_UPDATE_HEAD``) only completes the tree it verified.
"""

import pytest

from hermes_cli import update_cmd
from tests.hermes_cli.test_update_target_identity import git, update_tree  # noqa: F401  (shared fixture)


@pytest.mark.parametrize("case", ["valid", "wrong-head", "not-coordinator"])
def test_protected_update_completes_only_the_verified_checkout(update_tree, monkeypatch, case):  # noqa: F811
    t = update_tree
    monkeypatch.setenv("HERMES_PROTECTED_UPDATE_HEAD", t.base if case != "wrong-head" else t.wanted)
    monkeypatch.setenv("HERMES_UPDATE_COORDINATOR_ACTIVE", "0" if case == "not-coordinator" else "1")
    monkeypatch.setattr("hermes_cli.source_releases.resolve_source_target",
                        lambda *_a, **_k: pytest.fail("protected update selected another remote target"))
    if case == "valid":
        update_cmd._cmd_update_impl(t.args, False)
        assert len(t.requests) == 1
        assert t.requests[0]["expected_sha"] == t.base
        assert t.requests[0]["branch"] == "retained-branch"
    else:
        with pytest.raises(SystemExit) as error:
            update_cmd._cmd_update_impl(t.args, False)
        assert error.value.code == 1
        assert t.requests == []
    assert git(t.clone, "rev-parse", "HEAD") == t.base
    assert git(t.clone, "rev-parse", "origin/main") == t.base
