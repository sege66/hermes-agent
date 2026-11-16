"""ki66: the detached fallback gateway command never claims an external supervisor.

Only launchd's wrapped child passes ``--external-supervisor`` (fork commit 68bed1f7de9);
split out of the upstream-owned test_gateway_service.py.
"""

from pathlib import Path

import hermes_cli.gateway as gateway_cli


def test_detached_fallback_command_has_no_external_supervisor_marker(tmp_path, monkeypatch):
    profile_dir = tmp_path / ".hermes" / "profiles" / "mybot"
    profile_dir.mkdir(parents=True)
    monkeypatch.setattr(gateway_cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(profile_dir))
    monkeypatch.setattr(gateway_cli, "get_hermes_home", lambda: profile_dir)

    command = gateway_cli._gateway_run_command()

    assert command[-3:] == ["gateway", "run", "--replace"]
    assert "--external-supervisor" not in command
