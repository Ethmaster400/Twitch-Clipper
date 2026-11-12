import math
from datetime import date

from claud import budget
from claud.db import DB
from claud.twitch import Clip

UCFG = {"monthly_minutes": 300, "platforms": ["tiktok", "youtube"]}


def test_clip_minutes_counts_each_platform():
    assert budget.clip_minutes(45, UCFG) == 1.5
    assert budget.clip_minutes(45, {**UCFG, "count_each_platform": False}) == 0.75


def test_pacing_spreads_the_month():
    nov_1, nov_30 = date(2026, 11, 1), date(2026, 11, 30)
    # 300 min over 30 days of November: 10 min a day
    assert budget.minutes_left_today(UCFG, 0, 0, nov_1) == 10
    assert budget.minutes_left_today(UCFG, 6, 6, nov_1) == 4
    # quiet days roll over: on the last day with 200 used, all 100 left are available
    assert budget.minutes_left_today(UCFG, 200, 0, nov_30) == 100
    # used up: nothing until next month
    assert budget.minutes_left_today(UCFG, 300, 0, nov_30) == 0
    # pacing off: everything that's left, any day
    assert budget.minutes_left_today({**UCFG, "pace_evenly": False}, 50, 0, nov_1) == 250
    # no limit configured
    assert budget.minutes_left_today({}, 999, 999, nov_1) == math.inf


def test_usage_reads_posted_clip_lengths(tmp_path):
    db = DB(tmp_path / "t.db")
    for i, secs in enumerate((30, 60)):
        clip = Clip(id=f"c{i}", streamer="s", title="t", url="u", views=1, duration=secs, game_id="1")
        db.upsert_clip(clip)
        db.record_post(clip.id, "uploadpost", remote_id="req")
    failed = Clip(id="f", streamer="s", title="t", url="u", views=1, duration=600, game_id="1")
    db.upsert_clip(failed)
    db.record_post("f", "uploadpost", error="boom")          # failed posts don't count
    used_month, used_today = budget.usage(db, UCFG)
    assert used_month == used_today == 3.0                   # (30 + 60) s x 2 platforms
    assert "3.0 / 300 min used" in budget.summary(db, UCFG)
