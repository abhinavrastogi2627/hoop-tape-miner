"""Video times as text, one rule for every stage: `mmss` formats, `seconds` parses.

mmss(83.44) -> '01:23' (whole seconds, truncated), mmss(83.44, 1) -> '01:23.4' (rounded first, so 59.97 gives
'01:00.0', never '00:60.0'). Minutes run past 59 ('61:05'): clip markers, sheets and briefs use mm:ss of the video.
seconds() reads 'm:ss', 'mm:ss.s', 'h:mm:ss(.s)' or a number.
"""
from __future__ import annotations


def mmss(t: float, decimals: int = 0) -> str:
    """Seconds -> 'mm:ss' (decimals 0, truncated) or 'mm:ss.s' (decimals 1, rounded); negative times clamp to 0."""
    t = max(0.0, float(t))
    if decimals <= 0:
        s = int(t)
        return f"{s // 60:02d}:{s % 60:02d}"
    t = round(t, decimals)
    m = int(t // 60)
    return f"{m:02d}:{t - 60 * m:0{3 + decimals}.{decimals}f}"


def seconds(v) -> float:
    """'31:46.5' -> 1906.5, '1:02:03' -> 3723.0, '1:05' -> 65.0, 12 -> 12.0 (ValueError on other text)."""
    if isinstance(v, (int, float)):
        return float(v)
    out = 0.0
    for x in str(v).strip().split(":"):
        out = out * 60 + float(x)
    return out
