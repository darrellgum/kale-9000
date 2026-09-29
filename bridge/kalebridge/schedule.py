"""Fallback schedule math (light photoperiod, fan cycle) in the bot's timezone."""
from __future__ import annotations

import datetime as dt


def tzinfo(name: str | None):
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001  (no tzdata on this OS: fall back to local time)
            pass
    return dt.datetime.now().astimezone().tzinfo


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def light_on_at(ts: float, sched: dict, tz) -> bool:
    t = dt.datetime.fromtimestamp(ts, tz)
    m = t.hour * 60 + t.minute + t.second / 60
    on, off = _hm(sched["on"]), _hm(sched["off"])
    return on <= m < off if on < off else (m >= on or m < off)


def next_light_boundary(ts: float, sched: dict, tz) -> float:
    t = dt.datetime.fromtimestamp(ts, tz)
    cands = []
    for day in (0, 1, 2):
        d = (t + dt.timedelta(days=day)).date()
        for hm in (sched["on"], sched["off"]):
            m = _hm(hm)
            c = dt.datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=tz).timestamp()
            if c > ts + 0.5:
                cands.append(c)
    return min(cands)


def _midnight(ts: float, tz) -> float:
    t = dt.datetime.fromtimestamp(ts, tz)
    return dt.datetime(t.year, t.month, t.day, tzinfo=tz).timestamp()


def fan_on_at(ts: float, cyc: dict, tz) -> bool:
    on, off = int(cyc["on_min"]), int(cyc["off_min"])
    if off <= 0:
        return True
    pos = ((ts - _midnight(ts, tz)) / 60.0) % (on + off)
    return pos < on


def next_fan_boundary(ts: float, cyc: dict, tz) -> float | None:
    on, off = int(cyc["on_min"]), int(cyc["off_min"])
    if off <= 0:
        return None
    mid = _midnight(ts, tz)
    pos = ((ts - mid) / 60.0) % (on + off)
    nxt = ts + ((on - pos) if pos < on else (on + off - pos)) * 60
    tomorrow = _midnight(mid + 86400 + 7200, tz)  # the cycle restarts at local midnight
    return min(nxt, tomorrow) if tomorrow > ts else nxt
