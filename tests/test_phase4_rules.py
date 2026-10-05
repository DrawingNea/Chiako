import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.db import RollRow
from core.helpers import UserError
from core.recap import duration
from core.scheduling import parse_when
from core.stats import (
    by_user, describe_setting, distribution, expected_successes, leaderboard, luck_verdict, pool_verdict,
    roll_profile, summarize,
)

BERLIN = "Europe/Berlin"


def ts(*args, tz=BERLIN):
    return int(datetime(*args, tzinfo=ZoneInfo(tz)).timestamp())


def row(user, natural=None, total=0, expr="1d20", label=None, **extra):
    return RollRow(user, None, expr, label, total, natural, 0, **extra)


def faces_row(user, sides, values, **extra):
    return row(user, None, sum(values), f"{len(values)}d{sides}", kind="sum",
               faces=json.dumps({str(sides): values}), **extra)


# ---------------------------------------------------------------- stats

def test_summary():
    s = summarize([row(1, 20, 25), row(1, 1, 3), row(1, None, 40, "8d6"), row(1, None, 90, "3d20:climb")])
    assert s.rolls == 4 and s.d20 == [20, 1] and s.nat20 == 1 and s.nat1 == 1
    assert s.avg_d20 == 10.5
    assert s.best.total == 40, "3d20 leftover points must not count as a big roll"
    assert s.checks == 1 and s.checks_passed == 1


def test_luck_works_for_every_die():
    assert "Not enough" in luck_verdict(summarize([row(1, 20)] * 3))
    assert "Blessed" in luck_verdict(summarize([row(1, 15)] * 20))        # older rows: natural d20 only
    assert "Cursed" in luck_verdict(summarize([faces_row(1, 6, [1, 2, 1])] * 10))
    assert "Perfectly average" in luck_verdict(summarize([faces_row(1, 10, [1, 10, 5, 6])] * 5))
    s = summarize([faces_row(1, 6, [6, 6]), faces_row(1, 20, [1])])
    assert s.dice == 3 and s.luck == pytest.approx(100 * (1 + 1 - 1) / 3)


def test_expected_successes():
    assert expected_successes(5, 10, (">=", 8), None, None) == pytest.approx(1.5)
    assert expected_successes(5, 10, (">=", 8), 10, None) == pytest.approx(5 * 0.3 / 0.9)
    assert expected_successes(5, 10, (">=", 8), 10, 1) == pytest.approx(5 * 0.2 / 0.9)


def test_pool_stats_per_setting():
    rows = [
        row(1, None, 3, "5d10!>=8", kind="pool", setting="d10>=8!10", expected=1.6667,
            faces=json.dumps({"10": [10, 9, 8, 2, 1, 4]})),
        row(1, None, 0, "5d10!>=8", kind="pool", setting="d10>=8!10", expected=1.6667,
            faces=json.dumps({"10": [1, 2, 3, 4, 5]})),
        row(1, None, 2, "6d6>=5"),                              # logged before settings existed
    ]
    s = summarize(rows)
    a, b = s.pools["d10>=8!10"], s.pools["d6>=5"]
    assert (a.rolls, a.successes, a.zero, a.best, a.bonus_dice) == (2, 3, 1, 3, 1)
    assert a.expected == pytest.approx(3.3334) and b.expected == pytest.approx(2.0)
    assert s.best is None, "pool successes aren't totals"
    assert describe_setting("d10>=8!10f1") == "d10 pools · success at ≥ 8 · 10s explode · ≤ 1 cancels"
    assert pool_verdict(a) == "a bit unlucky", "3 successes where 3.33 were expected"


def test_profile_of_a_real_roll():
    import dice.engine as engine

    class Rigged:
        def __init__(self, values):
            self.values = list(values)

        def randint(self, a, b):
            return self.values.pop(0)

    old = engine._rng
    try:
        engine._rng = Rigged([10, 3, 8, 7])
        prof = roll_profile(engine.roll("3d10!>=8"))
        assert prof["kind"] == "pool" and prof["setting"] == "d10>=8!10"
        assert prof["faces"] == {"10": [10, 3, 8, 7]} and prof["expected"] == pytest.approx(1.0)
        engine._rng = Rigged([4, 2])
        prof = roll_profile(engine.roll("1d20+1d6+3"))
        assert prof == dict(kind="sum", setting=None, faces={"20": [4], "6": [2]}, expected=None)
    finally:
        engine._rng = old


def test_distribution():
    lines = distribution([20, 20, 1]).splitlines()
    assert len(lines) == 20 and lines[19].endswith(" 2") and lines[0].endswith(" 1") and "█" in lines[19]
    assert len(distribution([6, 1], 6).splitlines()) == 6
    assert distribution([]) == "no d20 rolls yet"


def test_leaderboard():
    users = by_user([row(1, 20), row(1, 20), row(2, 20), row(3, 5)])
    top = leaderboard(users, lambda s: s.nat20 or None)
    assert top == [(1, 2), (2, 1)]
    low = leaderboard(users, lambda s: s.luck, reverse=False)
    assert low[0][0] == 3


def test_duration():
    assert duration(59 * 60) == "59 min" and duration(3 * 3600 + 5 * 60) == "3h 05m"


# ---------------------------------------------------------------- dates

NOW = ts(2026, 10, 4, 20, 0)  # a Sunday evening


@pytest.mark.parametrize("text,expected", [
    ("2026-10-09 19:30", ts(2026, 10, 9, 19, 30)),
    ("09.10.2026 19:30", ts(2026, 10, 9, 19, 30)),
    ("9.10. 19:30", ts(2026, 10, 9, 19, 30)),
    ("9.10 7:30pm", ts(2026, 10, 9, 19, 30)),
    ("1.10. 19:00", ts(2027, 10, 1, 19, 0)),          # already passed this year
    ("tomorrow 19:30", ts(2026, 10, 5, 19, 30)),
    ("today 21:00", ts(2026, 10, 4, 21, 0)),
    ("fri 19:30", ts(2026, 10, 9, 19, 30)),
    ("Friday 8pm", ts(2026, 10, 9, 20, 0)),
    ("sun 19:00", ts(2026, 10, 11, 19, 0)),           # today, but already over -> next week
    ("2026-10-26 19:30", ts(2026, 10, 26, 19, 30)),   # after the daylight-saving switch
])
def test_parse_when(text, expected):
    assert parse_when(text, BERLIN, NOW) == expected


def test_daylight_saving_is_respected():
    before = parse_when("2026-10-24 19:30", BERLIN, NOW)
    after = parse_when("2026-10-26 19:30", BERLIN, NOW)
    assert after - before == 2 * 86400 + 3600  # clocks went back one hour in between


def test_other_time_zones():
    assert parse_when("2026-10-09 19:30", "America/New_York", NOW) == ts(2026, 10, 9, 19, 30, tz="America/New_York")


@pytest.mark.parametrize("text", ["today 19:00", "2025-01-01 10:00", "32.10. 19:00", "fri 25:00", "fri 19",
                                  "banana 19:00", "", "29.02.2027 10:00"])
def test_parse_when_errors(text):
    with pytest.raises(UserError):
        parse_when(text, BERLIN, NOW)


def test_timezone_names_ignore_case():
    from core.scheduling import get_zone
    assert get_zone("europe/berlin").key == "Europe/Berlin"
    assert get_zone("america/new york").key == "America/New_York"


def test_bad_timezone():
    with pytest.raises(UserError):
        parse_when("fri 19:30", "Mars/Olympus", NOW)
