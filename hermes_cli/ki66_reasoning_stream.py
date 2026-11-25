"""ki66 local: stream reasoning as logical lines so the terminal soft-wraps them.

Upstream ``_stream_reasoning_delta`` prints a hard newline every 80 characters.
A reflowing terminal only rewraps text that has no hard newline, and the resize
path leaves that text on screen. This module replaces the live methods.
"""

from __future__ import annotations

import time


def paint_reasoning_line(cli, line: str, *, final: bool) -> None:
    """Paint one reasoning line. An open line is rewritten in place as tokens arrive."""
    from cli import _DIM, _RST, _cprint
    painted = f"{_DIM}{line}{_RST}"
    previous = getattr(cli, "_reasoning_open_painted", None)
    _cprint(painted, replaces=previous, open_line=not final)
    cli._reasoning_open_painted = None if final else painted


def _emit_reasoning_buf(cli) -> None:
    while "\n" in cli._reasoning_buf:
        line, cli._reasoning_buf = cli._reasoning_buf.split("\n", 1)
        paint_reasoning_line(cli, line, final=True)
    if cli._reasoning_buf:
        paint_reasoning_line(cli, cli._reasoning_buf, final=False)


def _stream_reasoning_delta(self, text: str) -> None:
    """Stream reasoning as logical lines. The terminal wraps and reflows them."""
    from cli import _DIM, _RST, _cprint
    if not text:
        return
    self._reasoning_shown_this_turn = True
    if getattr(self, "_stream_box_opened", False):
        return
    if getattr(self, "_modern_layout", False):
        from hermes_cli.cli_modern_layout import separator
        if not getattr(self, "_reasoning_box_opened", False):
            self._reasoning_box_opened, self._reasoning_started_at = True, time.monotonic()
            self._reasoning_buf = ""
            self._reasoning_open_painted = None
            _cprint("\n" + separator(False))
        self._reasoning_buf = getattr(self, "_reasoning_buf", "") + text
        _emit_reasoning_buf(self)
        return
    if not getattr(self, "_reasoning_box_opened", False):
        from agent.i18n import t
        self._reasoning_box_opened = True
        self._reasoning_open_painted = None
        w = self._scrollback_box_width()
        r_label = f" {t('cli.chat.reasoning_label')} "
        r_fill = w - 2 - len(r_label)
        _cprint(
            f"\n{_DIM}┌─{r_label}{'─' * max(r_fill - 1, 0)}┐{_RST}",
            box_rule="top",
            box_label=r_label,
        )
    self._reasoning_buf = getattr(self, "_reasoning_buf", "") + text
    _emit_reasoning_buf(self)


def install(mixin) -> None:
    """Replace the live reasoning paint. Idempotent."""
    if getattr(mixin, "_ki66_reasoning_softwrap", False):
        return
    mixin._stream_reasoning_delta = _stream_reasoning_delta
    orig_close = mixin._close_reasoning_box

    def _close_reasoning_box(self) -> None:
        # The open line is already on screen. Printing the buffer again duplicates it.
        if getattr(self, "_reasoning_open_painted", None) is not None:
            self._reasoning_buf = ""
            self._reasoning_open_painted = None
        if getattr(self, "_modern_layout", False):
            orig_close(self)
            return
        if not getattr(self, "_reasoning_box_opened", False):
            return
        from cli import _DIM, _RST, _cprint
        tail = getattr(self, "_reasoning_buf", "")
        if tail:
            _cprint(f"{_DIM}{tail}{_RST}")
            self._reasoning_buf = ""
        w = self._scrollback_box_width()
        _cprint(f"{_DIM}└{'─' * (w - 2)}┘{_RST}", box_rule="bottom")
        self._reasoning_box_opened = False
        if not getattr(self, "_stream_box_live", False):
            self._release_held_status_lines()

    mixin._close_reasoning_box = _close_reasoning_box
    orig_reset = mixin._reset_stream_state

    def _reset_stream_state(self) -> None:
        orig_reset(self)
        self._reasoning_open_painted = None

    mixin._reset_stream_state = _reset_stream_state

    def _recover_after_resize(self, app, original_on_resize) -> None:
        from hermes_cli.cli_terminal_mixin import CLITerminalMixin
        prev = getattr(self, "_last_resize_width", None)
        rebuild = False
        try:
            rebuild = bool(self._redraw_rebuilds_scrollback())
        except Exception:
            rebuild = False
        if rebuild and isinstance(prev, int):
            try:
                pending = app.output.get_size().columns
            except Exception:
                pending = None
            if isinstance(pending, int) and pending > 0 and pending != prev:
                from hermes_cli.cli_render import refresh_classic_box_history
                refresh_classic_box_history(pending)
        CLITerminalMixin._recover_after_resize(self, app, original_on_resize)
        new = getattr(self, "_last_resize_width", None)
        if isinstance(prev, int) and isinstance(new, int) and prev != new and not rebuild:
            from hermes_cli.cli_render import retarget_classic_box_rules
            retarget_classic_box_rules(app)

    mixin._recover_after_resize = _recover_after_resize
    mixin._ki66_reasoning_softwrap = True
