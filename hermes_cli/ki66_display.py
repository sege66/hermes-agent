"""ki66 local-only: display-width aware wrapping for streamed text (CJK/emoji = 2 cells)."""


def _stream_display_width(text: str) -> int:
    """Terminal cell width of *text* (CJK/emoji = 2, ASCII = 1)."""
    try:
        from prompt_toolkit.utils import get_cwidth
        return get_cwidth(text or "")
    except Exception:
        return len(text or "")


def _cut_stream_at_display_width(text: str, max_width: int) -> tuple[str, str]:
    """Split *text* so the first part's display width is <= *max_width*."""
    if not text or max_width <= 0:
        return "", text or ""

    try:
        from prompt_toolkit.utils import get_cwidth
    except Exception:
        if len(text) <= max_width:
            return text, ""
        cut = text.rfind(" ", 0, max_width)
        if cut <= 0:
            cut = max_width
        return text[:cut], text[cut:].lstrip(" ")

    width = 0
    last_space = -1
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        cw = get_cwidth(ch)
        if width + cw > max_width:
            break
        if ch in (" ", "\t"):
            last_space = i
        width += cw
        i += 1
    else:
        return text, ""

    if i == 0:
        return text[:1], text[1:]

    if last_space > 0:
        return text[:last_space], text[last_space + 1 :].lstrip(" ")

    return text[:i], text[i:]
