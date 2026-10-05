"""
Dice statistics from the roll log.

Every roll is logged with the faces of all dice rolled, so luck can be judged for any die (d20, d10, d6, Fate)
and for success pools (actual successes compared with the expected number for the pool's rules).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from dice.engine import RollResult
from dice.systems import ThreeD20Result

from .db import RollRow

EXPECTED_D20 = 10.5
MIN_DICE_FOR_LUCK = 20
_POOL_RE = re.compile(r"^(\d+)d(\d+)(?:!(\d+)?)?(>=|<=|>|<|=)(\d+)(?:f(\d+))?$")  # pools logged before 'setting'
_SETTING_RE = re.compile(r"^d(\d+)(>=|<=|>|<|=)(\d+)(?:!(\d+))?(?:f(\d+))?$")
_COMPARE = {">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t, ">": lambda v, t: v > t,
            "<": lambda v, t: v < t, "=": lambda v, t: v == t}
_RULE = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "="}


# ------------------------------------------------------------------ what gets logged per roll

def pool_setting(sides: int, compare: tuple[str, int], explode: Optional[int], fail: Optional[int]) -> str:
    """A pool's rules as a short key: 'd10>=8!10f1'."""
    return f"d{sides}{compare[0]}{compare[1]}" + (f"!{explode}" if explode else "") + (f"f{fail}" if fail else "")


def expected_successes(count: int, sides: int, compare: tuple[str, int], explode: Optional[int],
                       fail: Optional[int]) -> Optional[float]:
    """Average successes for `count` dice: every die adds P(success) - P(cancel), and explosions add dice."""
    op, target = compare
    faces = range(1, sides + 1)
    p_success = sum(_COMPARE[op](v, target) for v in faces) / sides
    p_cancel = sum(not _COMPARE[op](v, target) and fail is not None and v <= fail for v in faces) / sides
    p_explode = sum(bool(explode) and v >= explode for v in faces) / sides
    if p_explode >= 1:
        return None
    return count * (p_success - p_cancel) / (1 - p_explode)


def roll_profile(result: RollResult) -> dict:
    """The extra log fields for a roll: kind, setting, faces, expected."""
    faces: dict[str, list[int]] = defaultdict(list)
    for term in result.terms:
        for d in term.dice:
            faces["F" if term.fate else str(term.sides)].append(d.value)
    pools = [t for t in result.terms if t.pool]
    setting, expected = None, None
    if pools:
        t = pools[0]
        setting = pool_setting(t.sides, t.compare, t.explode, t.fail)
        if not t.keep:
            parts = [expected_successes(p.count, p.sides, p.compare, p.explode, p.fail) for p in pools]
            expected = None if None in parts else round(sum(parts), 4)
    kind = "pool" if pools else "fate" if result.has_fate else "sum"
    return dict(kind=kind, setting=setting, faces=dict(faces) or None, expected=expected)


def check_profile(res: ThreeD20Result) -> dict:
    return dict(kind="3d20", setting=None, faces={"20": [d.roll for d in res.dice]}, expected=None)


def describe_setting(setting: str) -> str:
    """'d10>=8!10f1' -> 'd10 pools · success at ≥ 8 · 10s explode · ≤ 1 cancels'"""
    m = _SETTING_RE.match(setting or "")
    if not m:
        return f"Pools ({setting})"
    sides, op, target, explode, fail = m.groups()
    parts = [f"d{sides} pools", f"success at {_RULE[op]} {target}"]
    if explode:
        parts.append(f"{sides}s explode" if explode == sides else f"{explode}+ explode")
    if fail:
        parts.append(f"≤ {fail} cancels")
    return " · ".join(parts)


# ------------------------------------------------------------------ summaries

@dataclass
class PoolStats:
    rolls: int = 0
    successes: int = 0
    expected: float = 0.0
    expected_rolls: int = 0     # rolls with a known expected value
    expected_successes: int = 0  # successes in those rolls (to compare like with like)
    zero: int = 0               # rolls without a single success
    best: int = 0
    bonus_dice: int = 0         # dice added by explosions

    @property
    def average(self) -> float:
        return self.successes / self.rolls if self.rolls else 0.0


@dataclass
class Summary:
    rolls: int = 0
    d20: list[int] = field(default_factory=list)          # natural d20s of single-d20 rolls (crits & fumbles)
    best: Optional[RollRow] = None                          # biggest total of a normal (adding-up) roll
    faces: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    pools: dict[str, PoolStats] = field(default_factory=lambda: defaultdict(PoolStats))
    checks: int = 0                                         # 3d20 checks
    checks_passed: int = 0

    @property
    def nat20(self) -> int:
        return self.d20.count(20)

    @property
    def nat1(self) -> int:
        return self.d20.count(1)

    @property
    def avg_d20(self) -> Optional[float]:
        return sum(self.d20) / len(self.d20) if self.d20 else None

    @property
    def dice(self) -> int:
        return sum(len(v) for v in self.faces.values())

    @property
    def luck(self) -> Optional[float]:
        """How far above (+) or below (-) the middle face all dice landed, in % of the way to the top/bottom."""
        devs = []
        for sides, values in self.faces.items():
            if sides == "F":
                devs += values
            elif int(sides) >= 2:
                mid, half = (int(sides) + 1) / 2, (int(sides) - 1) / 2
                devs += [(v - mid) / half for v in values]
        return 100 * sum(devs) / len(devs) if devs else None


def _pool_info(row: RollRow) -> tuple[Optional[str], Optional[float]]:
    """A pool's setting and expected successes, also for rolls logged before those columns existed."""
    if row.kind == "pool":
        return row.setting, row.expected
    if row.kind is None and (m := _POOL_RE.match(row.expression.replace(" ", ""))):
        count, sides, explode, op, target, fail = m.groups()
        sides_i = int(sides)
        explode_i = (int(explode) if explode else sides_i) if "!" in row.expression else None
        fail_i = int(fail) if fail else None
        setting = pool_setting(sides_i, (op, int(target)), explode_i, fail_i)
        return setting, expected_successes(int(count), sides_i, (op, int(target)), explode_i, fail_i)
    return None, None


def summarize(rows: list[RollRow]) -> Summary:
    s = Summary()
    for r in rows:
        s.rolls += 1
        if r.natural is not None:
            s.d20.append(r.natural)
        dice = r.dice
        if not dice and r.natural is not None:  # older rolls only stored the natural d20
            dice = {"20": [r.natural]}
        for sides, values in dice.items():
            s.faces[sides] += values

        if r.kind == "3d20" or r.expression.startswith("3d20:"):
            s.checks += 1
            s.checks_passed += (r.total or 0) >= 0
            continue
        setting, expected = _pool_info(r)
        if setting:
            p = s.pools[setting]
            p.rolls += 1
            p.successes += r.total or 0
            p.zero += (r.total or 0) <= 0
            p.best = max(p.best, r.total or 0)
            if expected is not None:
                p.expected += expected
                p.expected_rolls += 1
                p.expected_successes += r.total or 0
            m = _SETTING_RE.match(setting)
            if m and m.group(4):
                p.bonus_dice += sum(v >= int(m.group(4)) for v in dice.get(m.group(1), []))
            continue
        if r.total is not None and (s.best is None or r.total > s.best.total):
            s.best = r
    return s


def by_user(rows: list[RollRow]) -> dict[int, Summary]:
    groups: dict[int, list[RollRow]] = defaultdict(list)
    for r in rows:
        groups[r.user_id].append(r)
    return {uid: summarize(rs) for uid, rs in groups.items()}


# ------------------------------------------------------------------ presentation helpers

def luck_verdict(s: Summary) -> str:
    if s.dice < MIN_DICE_FOR_LUCK:
        return f"Not enough dice yet to judge your luck ({s.dice}/{MIN_DICE_FOR_LUCK})"
    luck = s.luck
    detail = f" (your dice land {abs(luck):.1f}% {'above' if luck >= 0 else 'below'} average)"
    if luck >= 10:
        return "Blessed by the dice gods 🍀" + detail
    if luck >= 3:
        return "A bit lucky" + detail
    if luck > -3:
        return "Perfectly average" + detail
    if luck > -10:
        return "A bit unlucky" + detail
    return "Cursed dice 💤" + detail


def pool_verdict(p: PoolStats) -> str:
    if not p.expected_rolls or not p.expected:
        return ""
    ratio = p.expected_successes / p.expected
    if ratio >= 1.15:
        return "lucky"
    if ratio >= 1.03:
        return "a bit lucky"
    if ratio > 0.97:
        return "right on average"
    if ratio > 0.85:
        return "a bit unlucky"
    return "unlucky"


def die_order(faces: dict[str, list[int]]) -> list[str]:
    """Die types, most rolled first (Fate dice last)."""
    return sorted(faces, key=lambda k: (k == "F", -len(faces[k]), k))


def distribution(values: list[int], sides: int = 20, width: int = 14) -> str:
    """A text histogram of die results from 1 to `sides`."""
    if not values:
        return f"no d{sides} rolls yet"
    c = Counter(values)
    top = max(c.values())
    lines = []
    for face in range(1, sides + 1):
        n = c.get(face, 0)
        bar = "█" * round(width * n / top) if n else ""
        lines.append(f"{face:>2} │{bar:<{width}} {n}")
    return "\n".join(lines)


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "–"


def leaderboard(summaries: dict[int, Summary], key, *, reverse=True, minimum=None, limit=3):
    """Top users by key(summary). `minimum` filters summaries (e.g. enough rolls)."""
    items = [(uid, key(s)) for uid, s in summaries.items() if (minimum is None or minimum(s))]
    items = [(uid, v) for uid, v in items if v is not None]
    items.sort(key=lambda x: x[1], reverse=reverse)
    return items[:limit]
