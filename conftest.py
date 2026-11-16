"""ki66: local-only pytest adjustments for upstream-owned test files.

Upstream test modules stay byte-identical to upstream so updates never conflict on
them. The few things this host needs live here instead, keyed by node id so no
other test sees them:

* deselect upstream cases that assert the reset this fork replaces with a merge
  (``hermes_cli/update_ki66.merge_unique_local_commits``) — the ``*_ki66`` siblings
  assert the fork behaviour instead;
* pin environment probes that read the live install (the borrowed interpreter
  owns ``~/.hermes/hermes-agent``; PM extras such as edge-tts are installed here).

Upstream has no repository-root conftest.py, so this file never merges against one.
"""

from __future__ import annotations

import pytest

_DESELECT = (
    # ordinary same-branch history: upstream resets, the fork merges.
    "tests/hermes_cli/test_update_autostash.py::"
    "test_update_preserves_local_work_and_rescues_orphan_before_reset[ordinary-",
    "tests/hermes_cli/test_update_diverged_rescue_ref.py::"
    "test_hermes_update_keeps_local_commit_behind_a_rescue_ref",
)

_GATEWAY_LAUNCHD = (
    "tests/hermes_cli/test_gateway_service.py::TestProfileArg::"
    "test_launchd_plist_wraps_gateway_stderr_with_timestamps",
    "tests/hermes_cli/test_gateway_service.py::TestProfileArg::"
    "test_launchd_osascript_wrapper_round_trips_shell_hostile_paths",
)
_NO_PM_EXTRA = (
    "tests/tools/test_tts_deepinfra.py::test_unselected_cloud_credentials_do_not_expose_edge_tool",
    "tests/tools/test_tts_mistral.py::TestCheckTtsRequirementsMistral::test_mistral_key_missing_returns_false",
)
_NO_OWNING_INSTALL = (
    "tests/hermes_cli/test_update_target_identity.py::",
    "tests/hermes_cli/test_update_target_identity_ki66.py::",
)
_NO_RETARGET = (
    "tests/hermes_cli/test_update_autostash.py::test_update_preserves_local_work_and_rescues_orphan_before_reset",
)
_NO_GIT_GC = (
    "tests/hermes_cli/test_update_interrupted_pull.py::"
    "test_concurrent_launches_take_turns_and_all_rerun_from_the_restored_tree",
)


def pytest_collection_modifyitems(config, items):
    keep, dropped = [], []
    for item in items:
        (dropped if item.nodeid.startswith(_DESELECT) else keep).append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep


@pytest.fixture(autouse=True)
def _ki66_host_pins(request, monkeypatch):
    nodeid = request.node.nodeid
    if nodeid.startswith(_GATEWAY_LAUNCHD):
        # The launchd plist embeds PROJECT_ROOT's venv python; pin it off the live checkout.
        from hermes_cli import gateway as gateway_cli

        monkeypatch.setattr(gateway_cli, "PROJECT_ROOT", request.getfixturevalue("tmp_path"))
    if nodeid.startswith(_NO_PM_EXTRA):
        # The PM extra probe sees this host's installed edge-tts; CI has none.
        from tools import tts_tool

        monkeypatch.setattr(tts_tool, "_pm_extra_available", lambda extra: False)
    if nodeid.startswith(_NO_OWNING_INSTALL):
        # The borrowed interpreter owns the live install; the fixture owns its temp checkout.
        monkeypatch.setattr("hermes_cli.update_owning_install.owning_install_root", lambda *_: None)
    if nodeid.startswith(_NO_RETARGET):
        monkeypatch.setattr("hermes_cli.update_owning_install.retarget_to_owning_install", lambda *_: None)
    if nodeid.startswith(_NO_GIT_GC):
        # Background GC can remove loose objects while the local clone copies them.
        monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "gc.auto")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "0")
        monkeypatch.setenv("GIT_CONFIG_KEY_1", "maintenance.auto")
        monkeypatch.setenv("GIT_CONFIG_VALUE_1", "false")
