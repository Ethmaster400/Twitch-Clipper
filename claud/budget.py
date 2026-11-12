"""Keep Upload-Post uploads within the plan's monthly video-minutes allowance.

platforms.uploadpost.monthly_minutes sets the allowance. Each clip costs its length, times
the number of platforms when count_each_platform is on (the safe assumption). With
pace_evenly, the remaining minutes are spread over the rest of the month, so a busy week
can't use up the whole month; minutes a day leaves unused roll over to later days.
"""
from __future__ import annotations

import calendar
import math
from datetime import date


def clip_minutes(duration_s: float, ucfg: dict) -> float:
    per = len(ucfg.get("platforms") or ["tiktok", "youtube"]) if ucfg.get("count_each_platform", True) else 1
    return duration_s / 60 * per


def minutes_left_today(ucfg: dict, used_month: float, used_today: float, today: date | None = None) -> float:
    """Minutes that can still be sent today (math.inf when there's no monthly limit)."""
    limit = ucfg.get("monthly_minutes")
    if not limit:
        return math.inf
    remaining = limit - used_month
    if remaining <= 0:
        return 0.0
    if not ucfg.get("pace_evenly", True):
        return remaining
    today = today or date.today()
    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    todays_share = (limit - (used_month - used_today)) / days_left
    return max(0.0, min(remaining, todays_share - used_today))


def usage(db, ucfg: dict) -> tuple[float, float]:
    """(minutes used this month, minutes used today) on Upload-Post, from Claud's records."""
    month_s, today_s = db.seconds_posted("uploadpost")
    return clip_minutes(month_s, ucfg), clip_minutes(today_s, ucfg)


def summary(db, ucfg: dict) -> str:
    used_month, used_today = usage(db, ucfg)
    limit = ucfg.get("monthly_minutes")
    if not limit:
        return f"Upload-Post this month: {used_month:.1f} min (no monthly limit set)"
    left = minutes_left_today(ucfg, used_month, used_today)
    return (f"Upload-Post this month: {used_month:.1f} / {limit} min used; "
            f"{left:.1f} min left for today")
