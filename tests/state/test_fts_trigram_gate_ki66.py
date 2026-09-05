"""HERMES_DISABLE_FTS_TRIGRAM must hold on every index-creating path (ki66).

The gate exists because the trigram index dominates state.db: on this host it
was 53MB of a 135MB database (R3 surgery, 2026-07-18). It is a local ki66
feature, so upstream has no test for it and every refactor of the FTS layer is
free to reintroduce a path that rebuilds the index behind the gate's back.

That has now happened twice:

* 2026-08-04 — SessionDB was split into four sibling modules and the gate had
  to be re-ported to ``hermes_state_common.fts_trigram_disabled``.
* 2026-08-10 — upstream added ``_recover_stale_fts`` (atomic stale-index
  recovery). It decided what to rebuild purely from "does the table exist in
  this DB", so a single corruption-recovery pass silently restored the whole
  trigram index.

These tests pin the invariant itself rather than one call site: with the gate
on, no code path may leave a trigram table or trigger behind — while a corrupt
trigram index must still be DROPped, since leaving a broken vtable in the
schema helps nobody.
"""

import sqlite3

import pytest

from hermes_state import SessionDB
from hermes_state_common import _FTS_TRIGGERS

TRIGRAM_TRIGGERS = tuple(t for t in _FTS_TRIGGERS if "trigram" in t)


def _trigram_objects(db_path):
    raw = sqlite3.connect(str(db_path))
    try:
        rows = raw.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%trigram%'"
        ).fetchall()
    finally:
        raw.close()
    return sorted(r[0] for r in rows)


def _gate(monkeypatch, enabled):
    # os.environ wins over the .env file, so set it explicitly in both
    # directions — this host's .env already carries the gate.
    monkeypatch.setenv("HERMES_DISABLE_FTS_TRIGRAM", "1" if enabled else "0")


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A DB built with the gate OFF, so the trigram index really exists."""
    _gate(monkeypatch, False)
    db = SessionDB(db_path=tmp_path / "state.db")
    if not db._fts_enabled:
        db.close()
        pytest.skip("FTS5 unavailable in this build")
    if not db._trigram_available:
        db.close()
        pytest.skip("trigram tokenizer unavailable in this build")
    db.create_session("s1", source="test")
    db.append_message("s1", "user", "헤르메스 트라이그램 게이트 회귀 테스트")
    yield db
    try:
        db.close()
    except Exception:
        pass


class TestTrigramGateOnRecovery:
    def test_stale_recovery_drops_trigram_and_does_not_rebuild_it(
        self, seeded_db, tmp_path, monkeypatch
    ):
        """Gate on: recovery removes the trigram index and leaves it gone."""
        db_path = tmp_path / "state.db"
        assert _trigram_objects(db_path), "fixture should have built a trigram index"

        _gate(monkeypatch, True)
        legacy = seeded_db._db_has_legacy_inline_fts(seeded_db._conn.cursor())
        assert seeded_db._recover_stale_fts(seeded_db._conn.cursor(), legacy=legacy)
        seeded_db._conn.commit()

        assert _trigram_objects(db_path) == [], (
            "stale recovery rebuilt the trigram index while the gate was on"
        )
        assert seeded_db._trigram_available is False

    def test_recovery_keeps_base_fts_and_content_searchable(
        self, seeded_db, tmp_path, monkeypatch
    ):
        """Dropping trigram must not cost us the base index or any message."""
        _gate(monkeypatch, True)
        legacy = seeded_db._db_has_legacy_inline_fts(seeded_db._conn.cursor())
        seeded_db._recover_stale_fts(seeded_db._conn.cursor(), legacy=legacy)
        seeded_db._conn.commit()

        assert seeded_db._fts_enabled is True
        results = seeded_db.search_messages("헤르메스")
        assert results, "base FTS must still answer after the trigram drop"

    def test_dropped_trigram_stays_gone_across_reopen(
        self, seeded_db, tmp_path, monkeypatch
    ):
        """Once the index is gone, opening the DB must not bring it back.

        This is the invariant the live host depends on. Note what the gate
        does NOT do: opening a database that still HAS a trigram index leaves
        it in place — the gate suppresses creation, it is not a migration.
        That is why the live state.db kept syncing trigram rows for weeks with
        the gate on, and why removing it took an explicit DROP (2026-08-10).
        """
        db_path = tmp_path / "state.db"
        _gate(monkeypatch, True)
        legacy = seeded_db._db_has_legacy_inline_fts(seeded_db._conn.cursor())
        seeded_db._recover_stale_fts(seeded_db._conn.cursor(), legacy=legacy)
        seeded_db._conn.commit()
        assert _trigram_objects(db_path) == []
        seeded_db.close()

        reopened = SessionDB(db_path=db_path)
        try:
            assert _trigram_objects(db_path) == [], (
                "reopening under the gate resurrected the trigram index"
            )
            assert reopened._trigram_available is False
            # And the base index still answers, so the drop cost us nothing.
            assert reopened.search_messages("헤르메스")
        finally:
            reopened.close()


class TestTrigramGateOffIsUnchanged:
    def test_recovery_still_rebuilds_trigram_when_gate_is_off(
        self, seeded_db, tmp_path, monkeypatch
    ):
        """Guard the other direction: the gate must not become unconditional."""
        db_path = tmp_path / "state.db"
        _gate(monkeypatch, False)

        legacy = seeded_db._db_has_legacy_inline_fts(seeded_db._conn.cursor())
        assert seeded_db._recover_stale_fts(seeded_db._conn.cursor(), legacy=legacy)
        seeded_db._conn.commit()

        assert _trigram_objects(db_path), (
            "with the gate off, recovery must restore the trigram index"
        )
        assert seeded_db._trigram_available is True
