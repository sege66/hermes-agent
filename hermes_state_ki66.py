"""ki66 local-only helpers for the session store (kept out of upstream-owned modules)."""

import os

# ── ki66: HERMES_DISABLE_FTS_TRIGRAM gate ────────────────────────────────
# Ported from the pre-0.20 monolithic hermes_state.py (ki66 commits
# ce0f374a4 + f81ac2f3a). When set, the CJK trigram virtual table is never
# created or rebuilt and CJK search falls back to LIKE (same behavior as a
# missing trigram tokenizer). Keeps state.db from re-growing the ~54-84MB
# trigram index that the 2026-07 R3 surgery removed.

_TRUEISH = ("1", "true", "yes", "on")


def _fts_trigram_disabled_in_dotenv() -> bool:
    """Read the gate straight out of ``$HERMES_HOME/.env``.

    ki66: the gate must not depend on the caller having run
    ``load_hermes_dotenv()``. hermes_state is imported directly by ad-hoc
    scripts, one-off tools and anything that skips the hermes_cli
    entrypoints — none of those populate os.environ, so the gate read as
    "off" and the trigram index was silently recreated (2026-07-23
    recurrence, again on 07-28). Parsing the file here makes the gate
    self-sufficient: whoever opens state.db honours it.

    Deliberately a minimal KEY=VALUE scan, not python-dotenv: this runs on
    a path that must never fail, and the one key it needs has no quoting
    or interpolation.
    """
    try:
        home = os.environ.get("HERMES_HOME") or os.path.join(
            os.path.expanduser("~"), ".hermes"
        )
        with open(os.path.join(home, ".env"), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "HERMES_DISABLE_FTS_TRIGRAM":
                    return value.strip().strip("'\"").lower() in _TRUEISH
    except Exception:
        pass
    return False


def fts_trigram_disabled() -> bool:
    """True when HERMES_DISABLE_FTS_TRIGRAM disables the CJK trigram index.

    os.environ wins (so a caller can force the index on for one process);
    otherwise fall back to the .env file so entrypoint-less importers
    cannot silently rebuild the index.
    """
    raw = os.environ.get("HERMES_DISABLE_FTS_TRIGRAM", "").strip()
    if raw:
        return raw.lower() in _TRUEISH
    return _fts_trigram_disabled_in_dotenv()
