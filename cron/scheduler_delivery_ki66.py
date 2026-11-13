"""ki66 (local fork) cron delivery additions, kept out of upstream-owned
``cron/scheduler_delivery.py`` so upstream releases merge without conflicts.

What this adds, without editing the upstream function bodies:

* the chat-delivery log (``cron.jobs.record_cron_delivery``) is written once per
  run, and only when a target *confirmed* the text send — an in-flight
  confirmation timeout is assume-delivered (no resend) but carries no evidence;
* a standalone send whose result does not confirm delivery is an error;
* a dict result with a truthy in-band ``error`` is a rejection.

``scheduler_delivery.py`` carries a single hook: ``@wrap_deliver_result`` on
``_deliver_result``. The lane wrappers are installed lazily (and idempotently)
on each run by replacing module globals, which the upstream functions resolve
at call time.
"""

from __future__ import annotations

import functools
import logging
import sys
import threading

logger = logging.getLogger("cron.scheduler_delivery")

_MARK = "_ki66_wrapped"
_run = threading.local()


def _mod():
    return sys.modules["cron.scheduler_delivery"]


def _state():
    return getattr(_run, "state", None)


def _in_band_error(send_result) -> bool:
    # Object results skip this — MagicMock would make any attribute truthy.
    return isinstance(send_result, dict) and bool(send_result.get("error"))


def confirm_delivery(send_result, *args, **kwargs) -> bool:
    """Upstream ``_confirm_adapter_delivery`` plus the in-band error rejection."""
    if _in_band_error(send_result):
        return False
    return _mod()._confirm_adapter_delivery(send_result, *args, **kwargs)


def _wrap_confirm(orig):
    @functools.wraps(orig)
    def _confirm_adapter_delivery(send_result, *args, **kwargs):
        if _in_band_error(send_result):
            return False
        return orig(send_result, *args, **kwargs)
    return _confirm_adapter_delivery


def _wrap_live_send_text(orig):
    @functools.wraps(orig)
    def _live_send_text(*args, **kwargs):
        result = orig(*args, **kwargs)
        state = _state()
        if state is not None:
            adapter_ok, timed_out = result[0], result[1]
            state["live_text_confirmed"] = bool(adapter_ok) and not timed_out
        return result
    return _live_send_text


def _wrap_live_adapter(orig):
    @functools.wraps(orig)
    def _deliver_via_live_adapter(*args, **kwargs):
        state = _state()
        if state is not None:
            state["live_text_confirmed"] = False
        delivered = orig(*args, **kwargs)
        if state is not None and delivered and state["live_text_confirmed"]:
            state["confirmed"] = True
        return delivered
    return _deliver_via_live_adapter


def _wrap_standalone_send(orig):
    @functools.wraps(orig)
    def _standalone_send(t, *args, **kwargs):
        result, err = orig(t, *args, **kwargs)
        if err is not None:
            return result, err
        if confirm_delivery(result):
            state = _state()
            if state is not None:
                state["confirmed"] = True
            return result, err
        if _in_band_error(result):
            # Upstream turns the dict's own error into the delivery error.
            return result, err
        error = getattr(result, "error", None) if not isinstance(result, dict) else None
        err = f"delivery error: {error or 'unconfirmed send result'} (target {t.where})"
        logger.error("Job '%s': %s", t.job["id"], err)
        return None, err
    return _standalone_send


_WRAPPERS = {
    "_confirm_adapter_delivery": _wrap_confirm,
    "_live_send_text": _wrap_live_send_text,
    "_deliver_via_live_adapter": _wrap_live_adapter,
    "_standalone_send": _wrap_standalone_send,
}


def ensure_installed() -> None:
    """Wrap any lane function that is not wrapped yet (also covers a test's
    ``mock.patch`` of one of them, which then restores our wrapper on exit)."""
    mod = _mod()
    for name, wrap in _WRAPPERS.items():
        current = getattr(mod, name)
        if getattr(current, _MARK, False):
            continue
        wrapped = wrap(current)
        setattr(wrapped, _MARK, True)
        setattr(mod, name, wrapped)


def wrap_deliver_result(fn):
    @functools.wraps(fn)
    def _deliver_result(job, content, *args, **kwargs):
        ensure_installed()
        previous = _state()
        state = _run.state = {"confirmed": False, "live_text_confirmed": False}
        try:
            result = fn(job, content, *args, **kwargs)
        finally:
            _run.state = previous
        if state["confirmed"]:
            from cron.jobs import record_cron_delivery
            record_cron_delivery(job.get("id", ""), job.get("name", ""), content)
        return result
    return _deliver_result
