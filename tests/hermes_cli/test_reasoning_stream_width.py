"""Live reasoning is one logical line per model newline.

A reflowing terminal only rewraps text that has no hard newline. Tokens append
to that line and the previous paint is rewritten, so a later resize can reflow it.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def _content(paints, alphabet):
    kept = []
    for text, replaces, open_line in paints:
        line = _plain(text)
        if line and set(line) <= alphabet:
            kept.append((line, _plain(replaces) if replaces else None, open_line))
    return kept


@pytest.fixture
def reasoning_cli(monkeypatch):
    from cli import HermesCLI
    import cli as climod

    paints = []

    def capture(text, replaces=None, open_line=False, **_k):
        paints.append((text, replaces, open_line))

    cli = HermesCLI.__new__(HermesCLI)
    monkeypatch.setattr(climod, "_cprint", capture)
    monkeypatch.setattr(HermesCLI, "_scrollback_box_width", lambda self: 40)
    return cli, paints


@pytest.mark.parametrize("modern", [True, False])
def test_an_unbroken_run_stays_one_logical_line(reasoning_cli, modern):
    cli, paints = reasoning_cli
    cli._modern_layout = modern
    text = "x" * 100
    for char in text:
        cli._stream_reasoning_delta(char)

    content = _content(paints, {"x"})
    assert [line for line, _prev, _open in content] == [text[:i] for i in range(1, 101)]
    assert content[-1] == (text, text[:-1], True)
    assert cli._reasoning_buf == text


@pytest.mark.parametrize("modern", [True, False])
def test_korean_is_not_cut_at_eighty_characters(reasoning_cli, modern):
    cli, paints = reasoning_cli
    cli._modern_layout = modern
    text = "가" * 40
    for char in text:
        cli._stream_reasoning_delta(char)

    content = _content(paints, {"가"})
    assert content[-1][0] == text
    assert all(text.startswith(line) for line, _prev, _open in content)
    assert len(content) == 40


@pytest.mark.parametrize("modern", [True, False])
def test_a_model_newline_ends_the_logical_line(reasoning_cli, modern):
    cli, paints = reasoning_cli
    cli._modern_layout = modern
    cli._stream_reasoning_delta("hel")
    cli._stream_reasoning_delta("lo\nwor")

    content = _content(paints, set("helowr"))
    assert content == [
        ("hel", None, True),
        ("hello", "hel", False),
        ("wor", None, True),
    ]


@pytest.mark.parametrize("modern", [True, False])
def test_close_does_not_print_the_open_line_again(reasoning_cli, modern):
    cli, paints = reasoning_cli
    cli._modern_layout = modern
    cli._stream_reasoning_delta("hello there")
    cli._close_reasoning_box()

    content = _content(paints, set("hello there"))
    assert [line for line, _prev, _open in content] == ["hello there"]
    assert cli._reasoning_buf == ""
    assert cli._reasoning_open_painted is None


def test_live_method_is_the_softwrap_and_upstream_body_stays():
    from pathlib import Path
    from hermes_cli.cli_stream_mixin import CLIStreamMixin
    from hermes_cli.ki66_reasoning_stream import _stream_reasoning_delta, install

    assert CLIStreamMixin._stream_reasoning_delta is _stream_reasoning_delta
    install(CLIStreamMixin)
    assert CLIStreamMixin._stream_reasoning_delta is _stream_reasoning_delta
    source = Path(__file__).resolve().parents[2].joinpath("hermes_cli/cli_stream_mixin.py").read_text()
    assert source.count("len(self._reasoning_buf) > 80") == 2
    assert "_ki66_install_reasoning_softwrap(CLIStreamMixin)" in source


def test_open_line_rewrites_one_history_row(monkeypatch):
    import cli

    cli._configure_output_history(True, 50)
    monkeypatch.setattr(cli, "_pt_print", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_PT_ANSI", lambda text: text)
    try:
        cli._cprint("done")
        cli._cprint("a", open_line=True)
        cli._cprint("ab", replaces="a", open_line=True)
        cli._cprint("ab", replaces="ab", open_line=False)
        assert [str(line) for line in cli._OUTPUT_HISTORY] == ["done", "ab"]
        assert cli._OUTPUT_HISTORY[-1].open_line is False

        cli._configure_output_history(True, 50)
        cli._cprint("closed")
        cli._cprint("next", replaces="nope", open_line=True)
        assert [str(line) for line in cli._OUTPUT_HISTORY] == ["closed", "next"]
    finally:
        cli._configure_output_history(False, 200)


def test_char_by_char_reasoning_is_one_history_line(monkeypatch):
    import cli
    from cli import HermesCLI

    cli._configure_output_history(True, 50)
    monkeypatch.setattr(cli, "_pt_print", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_PT_ANSI", lambda text: text)
    try:
        cli_obj = HermesCLI.__new__(HermesCLI)
        cli_obj._modern_layout = True
        cli_obj._reset_stream_state()
        text = "가" * 40
        for char in text:
            cli_obj._stream_reasoning_delta(char)
        content = [line for line in cli._OUTPUT_HISTORY if "가" in str(line)]
        assert len(content) == 1
        assert text in content[0]
        assert content[0].open_line is True
        cli_obj._close_reasoning_box()
        content = [line for line in cli._OUTPUT_HISTORY if "가" in str(line)]
        assert len(content) == 1
    finally:
        cli._configure_output_history(False, 200)


def test_rewind_counts_visible_cells_at_the_current_width(monkeypatch):
    from hermes_cli.cli_render import _rewind_open_line

    calls = []

    class Out:
        def cursor_up(self, n):
            calls.append(n)

        def erase_down(self):
            pass

        def reset_attributes(self):
            pass

        def flush(self):
            pass

    monkeypatch.setattr("hermes_cli.cli_render._painted_columns", lambda: 10)
    _rewind_open_line(Out(), "\x1b[2m" + ("x" * 25) + "\x1b[0m")
    assert calls == [3]


def test_rewind_writes_nothing_when_stdout_is_not_a_tty(monkeypatch, capsys):
    from hermes_cli.cli_render import _rewind_open_line

    monkeypatch.setattr("hermes_cli.cli_render._painted_columns", lambda: 10)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    _rewind_open_line(None, "x" * 25)
    assert capsys.readouterr().out == ""


def test_widening_the_terminal_reflows_the_reasoning_line(tmp_path):
    """A real tmux pane joins the soft-wrapped sentence when the window grows.

    A hard newline every 80 characters would still split the sentence after the
    widen. A model newline stays a line break.
    """
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is not installed")
    sentence = "The reasoning stream keeps this sentence whole so a wider window can reflow it cleanly."
    first = "First logical line stays together across the resize boundary here."
    second = "Second logical line stays on its own row after the resize."
    script = tmp_path / "paint.py"
    script.write_text(
        "import sys, time\n"
        "sys.path.insert(0, '/Users/kihwangkim/.hermes/hermes-agent')\n"
        "from cli import HermesCLI\n"
        "def paint(text):\n"
        "    cli = HermesCLI.__new__(HermesCLI)\n"
        "    cli._modern_layout = True\n"
        "    cli._reset_stream_state()\n"
        "    for char in text:\n"
        "        cli._stream_reasoning_delta(char)\n"
        "    cli._close_reasoning_box()\n"
        f"paint({sentence!r})\n"
        f"paint({first + chr(10) + second!r})\n"
        "sys.stdout.write('\\nALL_DONE\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    socket = f"ki66-reflow-{os.getpid()}"
    base = [tmux, "-L", socket]
    subprocess.run([*base, "kill-server"], check=False, capture_output=True)
    try:
        subprocess.run(
            [*base, "new-session", "-d", "-s", "reflow", "-x", "40", "-y", "30",
             sys.executable, "-u", str(script)],
            check=True,
        )
        narrow = ""
        for _ in range(40):
            narrow = subprocess.run(
                [*base, "capture-pane", "-p", "-S", "-80", "-t", "reflow"],
                check=True, text=True, capture_output=True,
            ).stdout
            if "\nALL_DONE\n" in f"\n{narrow}":
                break
            time.sleep(0.25)
        else:
            raise AssertionError(narrow)
        subprocess.run([*base, "resize-window", "-t", "reflow", "-x", "140", "-y", "30"], check=True)
        time.sleep(0.4)
        wide = subprocess.run(
            [*base, "capture-pane", "-p", "-S", "-80", "-t", "reflow"],
            check=True, text=True, capture_output=True,
        ).stdout
    finally:
        subprocess.run([*base, "kill-server"], check=False, capture_output=True)

    rows = [row.strip() for row in wide.splitlines()]
    assert sum(row.count(sentence) for row in rows) == 1, wide
    assert first in rows, wide
    assert second in rows, wide
    assert not any(first in row and second in row for row in rows), wide


def test_replacing_an_open_line_charges_only_the_rows_it_grew(monkeypatch):
    import cli
    from hermes_cli import cli_render

    events = []
    size = SimpleNamespace(columns=10)

    class Output:
        def get_size(self):
            return size

        def cursor_up(self, n):
            events.append(("up", n))

        def erase_down(self):
            events.append("erase_down")

        def reset_attributes(self):
            pass

        def flush(self):
            pass

    class Renderer:
        _min_available_height = 0
        _last_screen = SimpleNamespace(height=0)

        def erase(self):
            events.append("renderer_erase")

        def reset(self):
            events.append("renderer_reset")

    class Loop:
        def call_soon_threadsafe(self, fn):
            fn()

    app = SimpleNamespace(
        _is_running=True,
        loop=Loop(),
        output=Output(),
        renderer=Renderer(),
        _running_in_terminal=False,
        _request_absolute_cursor_position=lambda: None,
        _redraw=lambda: None,
    )
    cli._configure_output_history(False, 20)
    cli_render._set_chrome_floor(20)
    monkeypatch.setattr("prompt_toolkit.application.get_app_or_none", lambda: app)
    monkeypatch.setattr("prompt_toolkit.renderer.print_formatted_text", lambda *a, **k: events.append("print"))
    try:
        cli._cprint("x" * 10, open_line=True)
        assert cli_render._chrome_floor() == 19
        assert not any(item[0] == "up" for item in events if isinstance(item, tuple))
        cli._cprint("x" * 25, replaces="x" * 10, open_line=True)
        assert ("up", 1) in events
        assert events.index("renderer_erase") < events.index(("up", 1))
        assert cli_render._chrome_floor() == 17
    finally:
        cli_render._set_chrome_floor(None)
        cli._configure_output_history(False, 200)


def _marked(text, kind, label=None):
    from hermes_cli.cli_render import _DIM, _PaintedLine, _RST

    line = _PaintedLine(f"{_DIM}{text}{_RST}")
    line.width = len(text)
    line.open_line = False
    line.box_rule = kind
    line.box_label = label
    return line


def test_classic_frame_is_marked_and_modern_is_not(monkeypatch):
    import cli
    from cli import HermesCLI

    cli._configure_output_history(True, 50)
    monkeypatch.setattr(cli, "_pt_print", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_PT_ANSI", lambda text: text)
    monkeypatch.setattr(HermesCLI, "_scrollback_box_width", lambda self: 40)
    try:
        obj = HermesCLI.__new__(HermesCLI)
        obj._modern_layout = False
        obj._reset_stream_state()
        obj._stream_reasoning_delta("hello")
        obj._close_reasoning_box()
        kinds = [getattr(line, "box_rule", None) for line in cli._OUTPUT_HISTORY]
        assert kinds.count("top") == 1
        assert kinds.count("bottom") == 1
        top = next(line for line in cli._OUTPUT_HISTORY if getattr(line, "box_rule", None) == "top")
        assert top.box_label.strip() != ""

        cli._OUTPUT_HISTORY.clear()
        obj._modern_layout = True
        obj._reset_stream_state()
        obj._reasoning_box_opened = False
        obj._stream_reasoning_delta("hello")
        obj._close_reasoning_box()
        assert all(getattr(line, "box_rule", None) is None for line in cli._OUTPUT_HISTORY)
    finally:
        cli._configure_output_history(False, 200)


def test_retarget_rewrites_classic_rules_from_the_prompt():
    import cli
    from hermes_cli.cli_render import classic_box_rule, retarget_classic_box_rules
    from prompt_toolkit.data_structures import Point

    wide_label = " Reasoning "
    assert len(classic_box_rule("top", 40, wide_label)) == 40
    assert len(classic_box_rule("bottom", 40)) == 40
    label = " AB "
    top10 = classic_box_rule("top", 10, label)
    bottom10 = classic_box_rule("bottom", 10)
    assert len(top10) == 10 and len(bottom10) == 10

    class Out:
        def __init__(self, columns):
            self.calls = []
            self.columns = columns

        def get_size(self):
            return SimpleNamespace(columns=self.columns, rows=24)

        def cursor_up(self, n):
            self.calls.append(("up", n))

        def cursor_down(self, n):
            self.calls.append(("down", n))

        def cursor_forward(self, n):
            self.calls.append(("forward", n))

        def write_raw(self, data):
            self.calls.append(("raw", data))

        def flush(self):
            self.calls.append("flush")

    def run(columns):
        out = Out(columns)
        app = SimpleNamespace(output=out, renderer=SimpleNamespace(_cursor_pos=Point(x=0, y=0)))
        cli._OUTPUT_HISTORY.clear()
        cli._OUTPUT_HISTORY.extend([
            "",
            _marked(top10, "top", label),
            "hello",
            _marked(bottom10, "bottom"),
        ])
        retarget_classic_box_rules(app)
        return out, [str(line) for line in cli._OUTPUT_HISTORY]

    cli._configure_output_history(True, 50)
    try:
        wide, history = run(20)
        ups = [item[1] for item in wide.calls if isinstance(item, tuple) and item[0] == "up"]
        assert ups == [1, 3]
        assert classic_box_rule("bottom", 20) in history[-1]
        assert classic_box_rule("top", 20, label) in history[1]
        again = Out(20)
        retarget_classic_box_rules(SimpleNamespace(
            output=again, renderer=SimpleNamespace(_cursor_pos=Point(x=0, y=0))))
        assert again.calls == []

        narrow, history = run(8)
        ups = [item[1] for item in narrow.calls if isinstance(item, tuple) and item[0] == "up"]
        assert ups == [2, 4]
        assert any(
            "\x1b[1M" in item[1]
            for item in narrow.calls
            if isinstance(item, tuple) and item[0] == "raw"
        )
        assert classic_box_rule("bottom", 8) in history[-1]
        assert classic_box_rule("top", 8, label) in history[1]

        mocked = SimpleNamespace(
            output=SimpleNamespace(get_size=lambda: SimpleNamespace(columns=object(), rows=object())),
            renderer=SimpleNamespace(_cursor_pos=Point(x=0, y=0)),
        )
        retarget_classic_box_rules(mocked)
    finally:
        cli._configure_output_history(False, 200)


def test_resize_wrapper_retargets_only_when_the_width_changes(monkeypatch):
    from hermes_cli.cli_stream_mixin import CLIStreamMixin
    from hermes_cli.cli_terminal_mixin import CLITerminalMixin

    events = []

    def orig(self, app, original_on_resize):
        events.append("orig")
        original_on_resize()
        self._last_resize_width = app.new_width

    monkeypatch.setattr(CLITerminalMixin, "_recover_after_resize", orig)
    monkeypatch.setattr(
        "hermes_cli.cli_render.retarget_classic_box_rules",
        lambda app: events.append("retarget"),
    )
    monkeypatch.setattr(
        "hermes_cli.cli_render.refresh_classic_box_history",
        lambda columns: events.append(("refresh", columns)),
    )
    cli = SimpleNamespace(_last_resize_width=40, _redraw_rebuilds_scrollback=lambda: False)
    app = SimpleNamespace(new_width=140, output=SimpleNamespace(get_size=lambda: SimpleNamespace(columns=140)))
    CLIStreamMixin._recover_after_resize(cli, app, lambda: events.append("original"))
    assert events == ["orig", "original", "retarget"]

    events.clear()
    cli._last_resize_width = 40
    app.new_width = 40
    CLIStreamMixin._recover_after_resize(cli, app, lambda: events.append("original"))
    assert events == ["orig", "original"]

    events.clear()
    cli._last_resize_width = 40
    cli._redraw_rebuilds_scrollback = lambda: True
    app.new_width = 90
    app.output = SimpleNamespace(get_size=lambda: SimpleNamespace(columns=90))
    CLIStreamMixin._recover_after_resize(cli, app, lambda: events.append("original"))
    assert events == [("refresh", 90), "orig", "original"]


def test_app_path_resize_redraws_the_classic_frame(tmp_path):
    """The production paint runs on the prompt_toolkit loop, then the frame follows the pane."""
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is not installed")
    sentence = "The reasoning stream keeps this sentence whole so a wider window can reflow it cleanly."
    label_path = tmp_path / "label.txt"
    ready = tmp_path / "ready"
    done = tmp_path / "done"
    script = tmp_path / "app_paint.py"
    script.write_text(
        "import os, sys, time, threading\n"
        "os.environ.setdefault('HERMES_DISABLE_LAZY_INSTALLS', '1')\n"
        "os.environ.setdefault('HERMES_LANGUAGE', 'en')\n"
        "sys.path.insert(0, '/Users/kihwangkim/.hermes/hermes-agent')\n"
        "os.chdir('/Users/kihwangkim/.hermes/hermes-agent')\n"
        "from prompt_toolkit.application import Application\n"
        "from prompt_toolkit.renderer import CPR_Support\n"
        "from prompt_toolkit.key_binding import KeyBindings\n"
        "from prompt_toolkit.layout import Layout\n"
        "from prompt_toolkit.layout.containers import Window\n"
        "from prompt_toolkit.layout.controls import FormattedTextControl\n"
        "from agent.i18n import t\n"
        "from cli import HermesCLI\n"
        "import cli\n"
        f"LABEL, READY, DONE = {str(label_path)!r}, {str(ready)!r}, {str(done)!r}\n"
        f"SENTENCE = {sentence!r}\n"
        "label = f\" {t('cli.chat.reasoning_label')} \"\n"
        "open(LABEL, 'w', encoding='utf-8').write(label)\n"
        "cli_obj = HermesCLI.__new__(HermesCLI)\n"
        "cli_obj._modern_layout = False\n"
        "cli_obj._reset_stream_state()\n"
        "kb = KeyBindings()\n"
        "app = Application(layout=Layout(Window(FormattedTextControl(lambda: 'prompt> '))),\n"
        "                  key_bindings=kb, full_screen=False, mouse_support=False)\n"
        "def paint():\n"
        "    for char in SENTENCE:\n"
        "        cli_obj._stream_reasoning_delta(char)\n"
        "    cli_obj._close_reasoning_box()\n"
        "    deadline = time.time() + 5\n"
        "    while time.time() < deadline:\n"
        "        kinds = [getattr(line, 'box_rule', None) for line in cli._OUTPUT_HISTORY]\n"
        "        if 'bottom' in kinds and any(SENTENCE in str(line) for line in cli._OUTPUT_HISTORY):\n"
        "            break\n"
        "        time.sleep(0.05)\n"
        "    time.sleep(0.5)\n"
        "    open(READY, 'w', encoding='utf-8').write('ready\\n')\n"
        "    while not os.path.exists(DONE):\n"
        "        time.sleep(0.05)\n"
        "    app.exit()\n"
        "def pre_run():\n"
        "    app.renderer.cpr_support = CPR_Support.NOT_SUPPORTED\n"
        "    cli_obj._install_resize_recovery(app)\n"
        "    threading.Thread(target=paint, daemon=True).start()\n"
        "app.run(pre_run=pre_run)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
    env["HERMES_LANGUAGE"] = "en"
    socket = f"ki66-app-reflow-{os.getpid()}"
    base = [tmux, "-L", socket]
    subprocess.run([*base, "kill-server"], check=False, capture_output=True)

    def pane():
        # The visible pane. Scrollback keeps the frame from before the resize.
        return subprocess.run(
            [*base, "capture-pane", "-p", "-t", "app"],
            check=True, text=True, capture_output=True,
        ).stdout

    try:
        subprocess.run(
            [*base, "new-session", "-d", "-s", "app", "-x", "40", "-y", "30",
             sys.executable, "-u", str(script)],
            check=True, env=env,
        )
        for _ in range(80):
            if ready.exists():
                break
            time.sleep(0.25)
        else:
            raise AssertionError(pane())
        time.sleep(0.6)
        narrow = pane()
        subprocess.run([*base, "resize-window", "-t", "app", "-x", "140", "-y", "30"], check=True)
        time.sleep(1.5)
        wide = pane()
        subprocess.run([*base, "resize-window", "-t", "app", "-x", "55", "-y", "30"], check=True)
        time.sleep(1.5)
        shrunk = pane()
    finally:
        done.write_text("done\n", encoding="utf-8")
        subprocess.run([*base, "kill-server"], check=False, capture_output=True)

    from hermes_cli.cli_render import classic_box_rule

    label = label_path.read_text(encoding="utf-8")
    rows = lambda text: [row.rstrip() for row in text.splitlines()]
    for width, captured in ((40, narrow), (140, wide), (55, shrunk)):
        lines = rows(captured)
        assert classic_box_rule("top", width, label) in lines, captured
        assert classic_box_rule("bottom", width) in lines, captured
        assert sum(line.startswith("┌") for line in lines) == 1, captured
        assert sum(line.startswith("└") for line in lines) == 1, captured
    assert not any(sentence in line for line in rows(narrow)), narrow
    assert any(sentence in line for line in rows(wide)), wide
    assert not any(sentence in line for line in rows(shrunk)), shrunk
    assert any(sentence[:24] in line for line in rows(shrunk)), shrunk
