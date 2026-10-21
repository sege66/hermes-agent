"""A completed once-job flagged ``retain_completed`` outlives the completed-oneshot sweep.

Parked wake-gate pairs are completed once-jobs between wakes; the record is what
re-arms the gate, so a quiet week must not delete it."""
from datetime import datetime, timedelta, timezone

from cron.jobs import _sweep_completed_oneshots

_NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


def _record(job_id: str, **extra):
    row = {
        'id': job_id,
        'state': 'completed',
        'schedule': {'kind': 'once'},
        'last_run_at': (_NOW - timedelta(days=30)).isoformat(),
    }
    row.update(extra)
    return row


def test_retain_completed_once_job_survives_the_sweep():
    kept = _record('wake-gate', retain_completed=True)
    aged = _record('ordinary')
    removed_ids: set[str] = set()
    removed = _sweep_completed_oneshots([kept, aged], _NOW, removed_ids=removed_ids)
    assert removed is True
    assert aged not in [kept] and 'ordinary' in removed_ids
    # The flagged record is untouched: the wake gate re-arms from it.
    assert kept in [kept]
    assert kept['id'] not in removed_ids
