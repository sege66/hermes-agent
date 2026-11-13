"""ki66 local-only tests for the google_api.py credential hooks (_google_api_ki66)."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


API_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills/productivity/google-workspace/scripts/google_api.py"
)

TOKEN = {
    "token": "ya29.test",
    "refresh_token": "1//refresh",
    "client_id": "123.apps.googleusercontent.com",
    "client_secret": "secret",
    "token_uri": "https://oauth2.googleapis.com/token",
}


@pytest.fixture
def api_module(monkeypatch, tmp_path):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    spec = importlib.util.spec_from_file_location("gws_api_ki66_test", API_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._ensure_authenticated = lambda: None
    module.TOKEN_PATH.write_text(json.dumps(TOKEN))
    return module


def test_gws_env_points_at_normalized_authorized_user_file(api_module):
    env = api_module._gws_env()

    path = Path(env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"])
    assert path == api_module.GWS_CREDENTIALS_PATH
    assert json.loads(path.read_text()) == {
        "client_id": TOKEN["client_id"],
        "client_secret": TOKEN["client_secret"],
        "refresh_token": TOKEN["refresh_token"],
        "type": "authorized_user",
    }
    assert path.stat().st_mode & 0o777 == 0o600


def test_gws_credentials_file_is_not_rewritten_when_unchanged(api_module):
    path = api_module._ensure_gws_credentials_file()
    before = path.stat().st_mtime_ns
    assert api_module._ensure_gws_credentials_file() == path
    assert path.stat().st_mtime_ns == before

    path.write_text("not json")
    api_module._ensure_gws_credentials_file()
    assert json.loads(path.read_text())["type"] == "authorized_user"


def test_gws_env_requires_the_token_file(api_module):
    api_module.TOKEN_PATH.unlink()
    with pytest.raises(FileNotFoundError):
        api_module._gws_env()


def test_refresh_error_prints_reauth_steps_and_exits(api_module, monkeypatch, capsys):
    class RefreshError(Exception):
        pass

    class FakeCredentials:
        expired = True
        refresh_token = "1//refresh"
        valid = True

        def refresh(self, _request):
            raise RefreshError("invalid_client")

    credentials_module = types.ModuleType("google.oauth2.credentials")
    credentials_module.Credentials = types.SimpleNamespace(
        from_authorized_user_file=lambda filename, scopes: FakeCredentials())
    exceptions_module = types.ModuleType("google.auth.exceptions")
    exceptions_module.RefreshError = RefreshError
    requests_module = types.ModuleType("google.auth.transport.requests")
    requests_module.Request = lambda: object()
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_module)
    monkeypatch.setitem(sys.modules, "google.auth.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_module)

    with pytest.raises(SystemExit) as excinfo:
        api_module.get_credentials()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "Google OAuth refresh failed: invalid_client" in err
    assert f"python {API_PATH.parent / 'setup.py'} --auth-url" in err
