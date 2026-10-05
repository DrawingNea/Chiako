"""Pure combat rules: damage, healing, health display and turn order. No Discord, no database."""
from __future__ import annotations

from typing import Optional, Sequence

from .db import Combatant, Condition


def apply_damage(hp: int, temp_hp: int, amount: int) -> tuple[int, int, int]:
    """Temp HP soaks damage first. HP never goes below 0. Returns (hp, temp_hp, absorbed_by_temp)."""
    amount = max(0, amount)
    absorbed = min(temp_hp, amount)
    return max(0, hp - (amount - absorbed)), temp_hp - absorbed, absorbed


def apply_heal(hp: int, max_hp: Optional[int], amount: int) -> int:
    new = hp + max(0, amount)
    return min(new, max_hp) if max_hp is not None else new


def apply_temp(temp_hp: int, amount: int) -> int:
    """Temp HP doesn't stack: keep the higher value."""
    return max(temp_hp, max(0, amount))


def hp_bar(hp: Optional[int], max_hp: Optional[int], width: int = 10) -> str:
    if hp is None:
        return "HP —"
    if not max_hp or max_hp <= 0:
        return f"HP {hp}"
    filled = round(width * max(0, min(hp, max_hp)) / max_hp)
    if hp > 0 and filled == 0:
        filled = 1
    return f"{'▰' * filled}{'▱' * (width - filled)} {hp}/{max_hp}"


def health_status(hp: Optional[int], max_hp: Optional[int]) -> str:
    """Vague health for monsters, so players don't see exact numbers."""
    if hp is None:
        return "Unknown"
    if hp <= 0:
        return "Down"
    if not max_hp:
        return "Hurt" if hp else "Down"
    if hp >= max_hp:
        return "Unhurt"
    if hp * 2 <= max_hp:
        return "Bloodied"
    return "Hurt"


def format_conditions(conditions: Sequence[Condition]) -> str:
    return ", ".join(c.label() for c in conditions)


def next_turn(order: Sequence[Combatant], current_id: Optional[int], round_: int,
              skip: Optional[set[int]] = None) -> tuple[Optional[int], int]:
    """
    Advance to the next combatant. Returns (new_current_id, new_round).
    round 0 = initiative phase -> starts round 1 with the first combatant.
    Combatants in `skip` (e.g. downed monsters) are passed over, unless everyone is skipped.
    """
    if not order:
        return None, round_
    skip = skip or set()
    ids = [c.id for c in order]

    if round_ == 0 or current_id not in ids:
        start, new_round = -1, max(round_, 1)
        if round_ == 0:
            new_round = 1
    else:
        start, new_round = ids.index(current_id), round_

    for step in range(1, len(ids) + 1):
        idx = start + step
        r = new_round + idx // len(ids) if start >= 0 else new_round
        candidate = ids[idx % len(ids)]
        if candidate not in skip:
            return candidate, r
    # everyone skipped: just move one step
    idx = start + 1
    return ids[idx % len(ids)], new_round + (idx // len(ids) if start >= 0 else 0)
