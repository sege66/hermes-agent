from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_cli import main as hermes_main
from hermes_cli import update_ki66


class ExecCalled(RuntimeError):
    pass


def _install_coordinator(home: Path) -> Path:
    coordinator = home / "bin" / "hermes-update-coordinator"
    coordinator.parent.mkdir(parents=True)
    coordinator.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    coordinator.chmod(0o755)
    return coordinator


def test_real_cli_update_execs_external_coordinator(tmp_path, monkeypatch):
    coordinator = _install_coordinator(tmp_path)
    captured: dict[str, object] = {}

    def fake_execve(path, argv, env):
        captured.update(path=path, argv=argv, env=env)
        raise ExecCalled

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_UPDATE_COORDINATOR_ACTIVE", raising=False)
    monkeypatch.setattr(
        hermes_main.sys,
        "argv",
        ["hermes", "update", "--yes", "--branch", "ki66"],
    )
    monkeypatch.setattr(hermes_main.os, "execve", fake_execve)

    with pytest.raises(ExecCalled):
        update_ki66.delegate_update_to_external_coordinator()

    assert captured["path"] == str(coordinator)
    assert captured["argv"] == [
        str(coordinator),
        "update",
        "--source",
        "hermes-cli",
        "--",
        "--yes",
        "--branch",
        "ki66",
    ]
    assert isinstance(captured["env"], dict)


def test_internal_worker_marker_prevents_recursion(tmp_path, monkeypatch):
    _install_coordinator(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_UPDATE_COORDINATOR_ACTIVE", "1")
    monkeypatch.setattr(hermes_main.sys, "argv", ["hermes", "update", "--yes"])

    assert update_ki66.delegate_update_to_external_coordinator() is False


def test_readonly_flags_bypass_coordinator(tmp_path, monkeypatch):
    _install_coordinator(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_UPDATE_COORDINATOR_ACTIVE", raising=False)
    monkeypatch.setattr(hermes_main.os, "execve", lambda *a: (_ for _ in ()).throw(AssertionError("must not exec")))

    for flag in ("--plan", "--check"):
        monkeypatch.setattr(hermes_main.sys, "argv", ["hermes", "update", flag])
        assert update_ki66.delegate_update_to_external_coordinator() is False


def test_programmatic_cmd_update_call_keeps_upstream_path(tmp_path, monkeypatch):
    _install_coordinator(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_UPDATE_COORDINATOR_ACTIVE", raising=False)
    monkeypatch.setattr(hermes_main.sys, "argv", ["pytest", "-q"])

    assert update_ki66.delegate_update_to_external_coordinator() is False


def test_cmd_update_delegates_before_upstream_preflight(monkeypatch):
    """main.cmd_update keeps its one-line ki66 hook ahead of the upstream path."""
    import hermes_cli.update_owning_install as owning

    monkeypatch.setattr(owning, "retarget_to_owning_install", lambda root: None)
    monkeypatch.setattr(update_ki66, "delegate_update_to_external_coordinator", lambda: True)
    monkeypatch.setattr(hermes_main, "_update_preflight_handled",
                        lambda args: (_ for _ in ()).throw(AssertionError("upstream path reached")))
    assert hermes_main.cmd_update(object()) is None
