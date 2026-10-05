"""Game-system specific checks: DSA-style 3d20 checks and PbtA move outcomes."""
from __future__ import annotations

from dataclasses import dataclass

from . import engine


@dataclass
class ThreeD20Die:
    attribute: str
    target: int      # attribute value + modifier
    roll: int
    overshoot: int   # skill points needed to make up for this die


@dataclass
class ThreeD20Result:
    dice: list[ThreeD20Die]
    points: int
    modifier: int
    remaining: int   # skill points left (negative = failed by that much)
    success: bool
    quality: int     # quality level 1-6 on success, else 0
    critical: bool   # two or more 1s
    botch: bool      # two or more 20s


def three_d20_check(attributes: list[tuple[str, int]], points: int, modifier: int = 0) -> ThreeD20Result:
    """Roll a d20 against each attribute; skill points pay for rolls above the attribute."""
    dice = []
    for name, value in attributes:
        target = value + modifier
        r = engine._rng.randint(1, 20)
        dice.append(ThreeD20Die(name, target, r, max(0, r - target)))

    remaining = points - sum(d.overshoot for d in dice)
    critical = sum(d.roll == 1 for d in dice) >= 2
    botch = sum(d.roll == 20 for d in dice) >= 2
    if critical:
        success, remaining = True, max(remaining, 0)
    elif botch:
        success = False
    else:
        success = remaining >= 0
    quality = min(6, max(1, (remaining + 2) // 3)) if success else 0
    return ThreeD20Result(dice, points, modifier, remaining, success, quality, critical, botch)


def pbta_outcome(total: int) -> tuple[str, str]:
    """(emoji, outcome): the emoji is empty for a weak hit."""
    if total >= 10:
        return "✨", "Strong hit"
    if total >= 7:
        return "", "Weak hit"
    return "💤", "Miss"
