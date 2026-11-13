"""ki66 local-only TTS helpers (kept out of the upstream-owned ``tools/tts_tool.py``).

``tools/tts_tool.py`` carries only the hook: one import line plus the three-line call in
``text_to_speech_tool``. Nothing here imports ``tools.tts_tool`` at module level (it imports
this module), so the tts_tool helpers are resolved lazily at call time — which also keeps
``monkeypatch.setattr(tts_tool, "_load_tts_config", ...)`` style test patches effective.
"""

import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple


# ===========================================================================
# Korean TTS reading normalization (ki66, restored 2026-10-10 from the
# 2026-07-13 stash): Korean voices read raw digits/units poorly ("23°C" is
# spelled out glyph by glyph, "$1,700" reads "dollar one seven zero zero").
# Upstream's ``tts_text_normalize`` targets English ("dollars", "percent"),
# so this block rewrites Korean readings for Korean-voice synthesis only.
# ===========================================================================
_KOREAN_DIGITS = ("영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구")
_KOREAN_SMALL_UNITS = ("", "십", "백", "천")
_KOREAN_LARGE_UNITS = ("", "만", "억", "조", "경")
_DOLLAR_AMOUNT_RE = re.compile(
    r"(?<![\w가-힣])(?P<lead>\s*)(?P<sign>[-−])?\s*(?P<prefix>US\$|\$|USD)\s*"
    r"(?P<amount>\d(?:[\d,]*\d)?(?:\.\d+)?)(?P<suffix>[KMBT])?(?![\dA-Za-z])",
    re.IGNORECASE,
)
_TEMPERATURE_RE = re.compile(
    r"(?P<lead>\s*)(?P<sign>[-−])?\s*(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?:°\s*C|℃|도\s*C|도씨)",
    re.IGNORECASE,
)
_WEATHER_DEGREE_RE = re.compile(
    r"(?P<context>(?:기온|온도|체감|현재|최고|최저|낮|아침|밤|새벽|오전|오후)[^\n]{0,12}?)"
    r"(?P<lead>\s*)(?P<sign>[-−])?\s*(?P<value>\d+(?:\.\d+)?)\s*도(?![A-Za-z])"
)
_PERCENT_RE = re.compile(r"(?P<sign>[+＋\-−])?\s*(?P<value>\d+(?:\.\d+)?)\s*%")
_INDEX_VALUE_RE = re.compile(
    r"(?P<name>에스앤피 오백|나스닥 종합|나스닥 백|나스닥|다우존스 산업평균|"
    r"다우 존스|코스피|코스닥|니케이 이백이십오|러셀 이천|빅스|풋시 백|닥스|항셍)"
    r"\s+(?P<value>\d[\d,]*(?:\.\d+)?)"
)
_STOCK_INDEX_REPLACEMENTS = (
    (re.compile(r"\bS\s*&\s*P\s*500\b", re.IGNORECASE), "에스앤피 오백"),
    (re.compile(r"\bNASDAQ\s+Composite\b", re.IGNORECASE), "나스닥 종합"),
    (re.compile(r"\bNASDAQ\s+100\b", re.IGNORECASE), "나스닥 백"),
    (re.compile(r"\bNASDAQ\b", re.IGNORECASE), "나스닥"),
    (re.compile(r"\bDow\s+Jones\s+Industrial\s+Average\b", re.IGNORECASE), "다우존스 산업평균"),
    (re.compile(r"\bDJIA\b", re.IGNORECASE), "다우존스 산업평균"),
    (re.compile(r"\bDow\s+Jones\b", re.IGNORECASE), "다우 존스"),
    (re.compile(r"\bKOSPI\b", re.IGNORECASE), "코스피"),
    (re.compile(r"\bKOSDAQ\b", re.IGNORECASE), "코스닥"),
    (re.compile(r"\bNikkei\s+225\b", re.IGNORECASE), "니케이 이백이십오"),
    (re.compile(r"\bRussell\s+2000\b", re.IGNORECASE), "러셀 이천"),
    (re.compile(r"\bFTSE\s+100\b", re.IGNORECASE), "풋시 백"),
    (re.compile(r"\bVIX\b", re.IGNORECASE), "빅스"),
    (re.compile(r"\bDAX\b", re.IGNORECASE), "닥스"),
    (re.compile(r"\bHang\s+Seng\b", re.IGNORECASE), "항셍"),
)

def _under_10000_to_korean(number: int) -> str:
    parts = []
    for power in range(3, -1, -1):
        unit_value = 10 ** power
        digit = number // unit_value
        number %= unit_value
        if digit == 0:
            continue
        unit = _KOREAN_SMALL_UNITS[power]
        if power > 0 and digit == 1:
            parts.append(unit)
        else:
            parts.append(f"{_KOREAN_DIGITS[digit]}{unit}")
    return "".join(parts)

def _int_to_korean(number: int) -> str:
    if number == 0:
        return _KOREAN_DIGITS[0]
    if number < 0:
        return f"마이너스 {_int_to_korean(abs(number))}"

    groups = []
    while number:
        groups.append(number % 10000)
        number //= 10000

    parts = []
    for idx in range(len(groups) - 1, -1, -1):
        group = groups[idx]
        if group == 0:
            continue
        parts.append(f"{_under_10000_to_korean(group)}{_KOREAN_LARGE_UNITS[idx]}")
    return "".join(parts)

def _decimal_text_to_korean(value: str) -> str:
    normalized = value.replace(",", "").strip()
    if not normalized:
        return ""
    if "." not in normalized:
        return _int_to_korean(int(normalized))
    integer, decimal = normalized.split(".", 1)
    decimal = decimal.rstrip()
    if not decimal:
        return _int_to_korean(int(integer or "0"))
    spoken_decimal = " ".join(_KOREAN_DIGITS[int(char)] for char in decimal if char.isdigit())
    return f"{_int_to_korean(int(integer or '0'))} 점 {spoken_decimal}"

def _format_temperature_reading(match: re.Match[str]) -> str:
    value = match.group("value")
    sign = match.group("sign")
    lead = match.groupdict().get("lead", "")
    spoken = _decimal_text_to_korean(value)
    if sign:
        return f"{lead}영하 {spoken} 도"
    if Decimal(value) == 0:
        return f"{lead}영 도"
    return f"{lead}영상 {spoken} 도"

def _format_weather_degree_reading(match: re.Match[str]) -> str:
    return f"{match.group('context')}{_format_temperature_reading(match)}"

def _format_dollar_reading(match: re.Match[str]) -> str:
    amount_text = match.group("amount").replace(",", "")
    suffix = (match.group("suffix") or "").upper()
    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        return match.group(0)

    lead = match.group("lead") or ""
    sign = "마이너스 " if match.group("sign") else ""
    multipliers = {
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
        "B": Decimal("1000000000"),
        "T": Decimal("1000000000000"),
    }
    if suffix:
        total = (amount * multipliers[suffix]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{lead}{sign}{_int_to_korean(int(total))} 달러"

    dollars = int(amount)
    cents = int(((amount - Decimal(dollars)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents == 100:
        dollars += 1
        cents = 0

    spoken = f"{lead}{sign}{_int_to_korean(dollars)} 달러"
    if cents:
        spoken = f"{spoken} {_int_to_korean(cents)} 센트"
    return spoken

def _format_percent_reading(match: re.Match[str]) -> str:
    sign = match.group("sign")
    prefix = ""
    if sign in {"+", "＋"}:
        prefix = "플러스 "
    elif sign in {"-", "−"}:
        prefix = "마이너스 "
    return f"{prefix}{_decimal_text_to_korean(match.group('value'))} 퍼센트"

def _format_index_value_reading(match: re.Match[str]) -> str:
    return f"{match.group('name')} {_decimal_text_to_korean(match.group('value'))}"

def _looks_like_korean_tts(provider: str, tts_config: Dict[str, Any]) -> bool:
    provider_cfg = tts_config.get(provider) if isinstance(tts_config.get(provider), dict) else {}
    voice = str(provider_cfg.get("voice") or provider_cfg.get("voice_id") or "")
    language = str(provider_cfg.get("language") or tts_config.get("language") or "")
    instructions = str(provider_cfg.get("instructions") or "")

    return (
        voice.lower().startswith("ko-kr")
        or language.lower().startswith("ko")
        or "korean" in instructions.lower()
        or "한국어" in instructions
    )

def _should_normalize_korean_tts_reading(provider: str, tts_config: Dict[str, Any]) -> bool:
    config = tts_config.get("korean_reading") if isinstance(tts_config.get("korean_reading"), dict) else {}
    enabled = config.get("enabled") if config else tts_config.get("korean_reading_enabled")
    if isinstance(enabled, str) and enabled.strip().lower() == "auto":
        enabled = None
    if enabled is not None:
        from tools.tts_tool_providers import _config_bool
        return _config_bool(enabled, default=False)
    return _looks_like_korean_tts(provider, tts_config)

def _normalize_korean_tts_reading(text: str, provider: str, tts_config: Dict[str, Any]) -> str:
    """Rewrite terse finance/weather notation into Korean spoken forms."""
    if not _should_normalize_korean_tts_reading(provider, tts_config):
        return text

    normalized = _TEMPERATURE_RE.sub(_format_temperature_reading, text)
    normalized = _WEATHER_DEGREE_RE.sub(_format_weather_degree_reading, normalized)
    normalized = _DOLLAR_AMOUNT_RE.sub(_format_dollar_reading, normalized)
    for pattern, replacement in _STOCK_INDEX_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = _INDEX_VALUE_RE.sub(_format_index_value_reading, normalized)
    normalized = _PERCENT_RE.sub(_format_percent_reading, normalized)
    return normalized


class _DropRecords(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def _ki66_korean_reading(
    text: str, speed: Optional[float], provider: Optional[str], voice_id: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Hook for ``text_to_speech_tool`` -> ``(text, error_json)``.

    Korean reading normalization must run BEFORE the shared English cleaner:
    prepare_spoken_text rewrites "23°C"→"23 degrees Celsius" and "$12.34"→"12.34 dollars",
    which destroys the Korean patterns. The provider/voice resolution it needs is the same
    one upstream runs right after the cleaner, so it is resolved here first (returning the
    voice_id error at the same point as before the split) and upstream then repeats it. The
    voice-override warning is muted for this first pass so it is still logged exactly once;
    the provider-override warning is already once-per-process.
    """
    import tools.tts_tool as _tts_tool

    tts_config, resolved = _tts_tool._apply_call_overrides(
        _tts_tool._load_tts_config(), speed, provider)
    mute = _DropRecords()
    _tts_tool.logger.addFilter(mute)
    try:
        tts_config, error = _tts_tool._apply_voice_override(tts_config, resolved, voice_id)
    finally:
        _tts_tool.logger.removeFilter(mute)
    if error:
        return text, error
    return _normalize_korean_tts_reading(text, resolved, tts_config), None
