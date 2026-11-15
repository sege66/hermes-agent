"""ki66 local-only helpers for ``google_api.py`` (upstream never touches this file).

``google_api.py`` runs as a standalone script and puts its own directory on
``sys.path``, so this sibling is imported the same way as ``_hermes_home``.
Paths and helpers are passed in by the caller: tests monkeypatch
``google_api.TOKEN_PATH`` and friends, so nothing is captured at import time.

gws 0.3.4 also drops array query params, which is why ``google_api.py`` omits
``metadataHeaders`` in ``gmail_search`` / ``gmail_reply`` (2026-09-19): with it
the metadata format returned zero headers; without it all headers come back and
``_headers_dict`` filters.
"""

import functools
import json
import sys
from pathlib import Path


def ensure_gws_credentials_file(token_path: Path, credentials_path: Path, normalize) -> Path:
    """Write the ``authorized_user`` file the gws CLI expects, derived from the Hermes token."""
    token = normalize(json.loads(token_path.read_text()))
    payload = {
        "client_id": token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "type": "authorized_user",
    }
    existing = None
    if credentials_path.exists():
        try:
            existing = json.loads(credentials_path.read_text())
        except Exception:
            existing = None
    if existing != payload:
        credentials_path.write_text(json.dumps(payload, indent=2))
        credentials_path.chmod(0o600)
    return credentials_path


def exit_on_refresh_error(get_credentials, scripts_dir: Path):
    """Wrap ``get_credentials``: a RefreshError prints re-auth steps and exits 1.

    Applied as a reassignment after the upstream ``get_credentials`` definition so
    its body (``creds.refresh(Request())``) stays byte-identical to upstream.
    """
    @functools.wraps(get_credentials)
    def wrapper(*args, **kwargs):
        try:
            from google.auth.exceptions import RefreshError
        except ImportError:  # google-auth absent/stubbed: nothing to translate
            return get_credentials(*args, **kwargs)
        try:
            return get_credentials(*args, **kwargs)
        except RefreshError as exc:
            _print_reauth_and_exit(exc, scripts_dir)
    return wrapper


def _print_reauth_and_exit(exc, scripts_dir: Path) -> None:
    print(f"Google OAuth refresh failed: {exc}", file=sys.stderr)
    print("Re-run Google Workspace OAuth setup with a valid client secret.", file=sys.stderr)
    print(f"  python {scripts_dir / 'setup.py'} --client-secret /path/to/client_secret.json", file=sys.stderr)
    print(f"  python {scripts_dir / 'setup.py'} --auth-url", file=sys.stderr)
    print(f"  python {scripts_dir / 'setup.py'} --auth-code CODE_OR_REDIRECT_URL", file=sys.stderr)
    sys.exit(1)
