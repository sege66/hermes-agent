from __future__ import annotations

import os
from pathlib import Path

import pytest

from hermes_cli import main as hermes_main


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
        hermes_main._delegate_update_to_external_coordinator()

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

    assert hermes_main._delegate_update_to_external_coordinator() is False


def test_readonly_flags_bypass_coordinator(tmp_path, monkeypatch):
    _install_coordinator(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_UPDATE_COORDINATOR_ACTIVE", raising=False)
    monkeypatch.setattr(hermes_main.os, "execve", lambda *a: (_ for _ in ()).throw(AssertionError("must not exec")))

    for flag in ("--plan", "--check"):
        monkeypatch.setattr(hermes_main.sys, "argv", ["hermes", "update", flag])
        assert hermes_main._delegate_update_to_external_coordinator() is False


def test_programmatic_cmd_update_call_keeps_upstream_path(tmp_path, monkeypatch):
    _install_coordinator(tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("HERMES_UPDATE_COORDINATOR_ACTIVE", raising=False)
    monkeypatch.setattr(hermes_main.sys, "argv", ["pytest", "-q"])

    assert hermes_main._delegate_update_to_external_coordinator() is False
