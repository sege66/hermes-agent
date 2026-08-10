"""Invariant guard for Telegram transport-error redaction.

Commit a04fcbf77 ("widen transport-error redaction to all remaining raw ...")
applied a naive ``s/error/_redact_telegram_error_text(error)/`` that matched the
word "error" *inside two format strings* instead of the argument. The result:

    logger.warning("[%s] Telegram network _redact_telegram_error_text(error), "
                   "scheduling reconnect: %s", self.name, error)

The message became nonsense AND the raw error kept reaching the log — the exact
leak the commit meant to close. Telegram puts the bot token in the request URL,
so an unredacted transport error can carry the token into gateway.log.

These tests pin both halves of the invariant so a future search-and-replace over
the upstream tree fails loudly instead of silently reopening the hole.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ADAPTER = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "platforms"
    / "telegram"
    / "adapter.py"
)

REDACTOR = "_redact_telegram_error_text"

# The two sites the botched sed hit, keyed by their format-string prefix.
GUARDED_LOG_SITES = (
    "[%s] Telegram network error, scheduling reconnect:",
    "[%s] Telegram polling error:",
)


@pytest.fixture(scope="module")
def adapter_tree() -> ast.Module:
    return ast.parse(ADAPTER.read_text(encoding="utf-8"), filename=str(ADAPTER))


def test_redactor_name_never_appears_inside_a_string_literal(adapter_tree):
    """A redactor *call* belongs in code, never baked into a format string."""
    offenders = [
        (node.lineno, node.value)
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and f"{REDACTOR}(" in node.value
    ]
    assert not offenders, (
        f"{REDACTOR}( found inside string literal(s) — a search-and-replace hit "
        f"the format string instead of the argument: {offenders}"
    )


def _logger_calls(tree: ast.Module):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "logger":
                yield node


@pytest.mark.parametrize("prefix", GUARDED_LOG_SITES)
def test_polling_error_sites_log_redacted_text(adapter_tree, prefix):
    """The polling-error log sites must pass the error through the redactor."""
    matches = [
        call
        for call in _logger_calls(adapter_tree)
        if call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and call.args[0].value.startswith(prefix)
    ]
    assert matches, f"no logger call found with format prefix {prefix!r}"

    for call in matches:
        redacted = any(
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Name)
            and arg.func.id == REDACTOR
            for arg in call.args[1:]
        )
        assert redacted, (
            f"line {call.lineno}: {prefix!r} logs its error without "
            f"{REDACTOR}() — raw Telegram errors can carry the bot token"
        )

        # exc_info re-emits the exception repr, which is the very string the
        # redactor masks; it would reopen the leak behind the redactor's back.
        exc_info = next(
            (kw for kw in call.keywords if kw.arg == "exc_info"), None
        )
        assert exc_info is None or exc_info.value.value is False, (
            f"line {call.lineno}: exc_info on a redacted Telegram error site "
            f"leaks the unredacted traceback"
        )


def test_redactor_masks_a_bot_token_in_a_transport_error():
    """End-to-end: the redactor actually removes a token from a URL error."""
    import sys

    sys.path.insert(0, str(ADAPTER.parents[3]))
    from agent.redact import redact_sensitive_text

    # Synthetic, non-functional stand-in shaped like a Telegram bot token.
    # Assembled from parts so credential scanners do not flag the fixture.
    shaped_like_a_token = ":".join(["123456789", "AA" + "F" * 33])
    message = (
        f"error sending request for url "
        f"(https://api.telegram.org/bot{shaped_like_a_token}/getUpdates)"
    )
    assert shaped_like_a_token not in redact_sensitive_text(message, force=True)
