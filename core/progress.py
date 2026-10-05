"""XP & levels, and resources (spell slots, ammo...). Pure logic plus small DB helpers."""
from __future__ import annotations

import re
from typing import Optional

from dice.engine import DiceError

from .db import Character, Database, Resource
from .helpers import UserError, load_sheet
from .i18n import t

XP_PRESETS = {
    "dnd5e": [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000, 120000,
              140000, 165000, 195000, 225000, 265000, 305000, 355000],
    "pathfinder": [0, 2000, 5000, 9000, 15000, 23000, 35000, 51000, 75000, 105000, 155000, 220000, 315000,
                   445000, 635000, 890000, 1300000, 1800000, 2550000, 3600000],
}

RESET_LABELS = {"short": "short rest", "long": "long rest", "never": "manual"}


def parse_xp_table(text: str) -> Optional[list[int]]:
    """'dnd5e', 'none' or '0, 1000, 3000, ...' (XP needed for level 1, 2, 3...)."""
    text = text.strip().lower()
    if text in ("none", "off", ""):
        return None
    if text in XP_PRESETS:
        return XP_PRESETS[text]
    try:
        values = [int(x) for x in re.split(r"[,\s;]+", text) if x]
    except ValueError:
        raise UserError("Use a preset (`dnd5e`, `pathfinder`, `none`) or numbers like `0, 1000, 3000, 6000`.")
    if not values or values[0] != 0:
        values = [0] + values
    if any(b <= a for a, b in zip(values, values[1:])):
        raise UserError("XP thresholds must go up, e.g. `0, 1000, 3000, 6000`.")
    if len(values) > 100:
        raise UserError("That's a lot of levels. Max 100.")
    return values


def level_for(xp: int, table: list[int]) -> int:
    return max(1, sum(1 for t in table if xp >= t))


def xp_progress(xp: int, table: Optional[list[int]], lang: str = "en") -> str:
    if not table:
        return t(lang, "{xp} XP", xp=f"{xp:,}")
    lvl = level_for(xp, table)
    if lvl >= len(table):
        return t(lang, "{xp} XP · level {lvl} (max)", xp=f"{xp:,}", lvl=lvl)
    lo, hi = table[lvl - 1], table[lvl]
    filled = round(10 * (xp - lo) / (hi - lo))
    return t(lang, "{xp} XP · level {lvl} · {bar} {left} to level {next}", xp=f"{xp:,}", lvl=lvl,
             bar="▰" * filled + "▱" * (10 - filled), left=f"{hi - xp:,}", next=lvl + 1)


async def apply_xp(db: Database, character: Character, new_xp: int, table: Optional[list[int]]) -> Optional[int]:
    """Store XP. If a level threshold is crossed, update a numeric `level` stat. Returns the new level if it changed."""
    old_xp = await db.get_xp(character.id)
    await db.set_xp(character.id, max(0, new_xp))
    if not table:
        return None
    old_lvl, new_lvl = level_for(old_xp, table), level_for(max(0, new_xp), table)
    if old_lvl == new_lvl:
        return None
    stats = await db.get_stats(character.id)
    current = stats.get("level")
    if current is None or re.fullmatch(r"\s*-?\d+\s*", current):  # don't overwrite a formula
        await db.set_stat(character.id, "level", str(new_lvl))
    return new_lvl


# --------------------------------------------------------------------------- resources

async def resource_max(db: Database, character: Character, r: Resource) -> int:
    sheet = await load_sheet(db, character)
    try:
        return sheet.resolve_formula(r.max_formula)
    except DiceError as e:
        raise UserError(f"Max of `{r.name}` (`{r.max_formula}`) doesn't work: {e}")


async def resources_line(db: Database, character: Character) -> str:
    out = []
    for r in (await db.get_resources(character.id)).values():
        try:
            mx = await resource_max(db, character, r)
        except UserError:
            mx = "?"
        out.append(f"{r.name} {r.current}/{mx}")
    return " · ".join(out)


async def rest(db: Database, character: Character, kind: str, restore_hp: bool) -> list[str]:
    """Reset resources (short: 'short' ones, long: 'short' + 'long'). Long rest can restore HP."""
    kinds = {"short"} if kind == "short" else {"short", "long"}
    changes = []
    for r in (await db.get_resources(character.id)).values():
        if r.reset in kinds:
            mx = await resource_max(db, character, r)
            if r.current != mx:
                changes.append(f"{r.name} {r.current}→{mx}")
                await db.update_resource_current(character.id, r.name, mx)
    if kind == "long" and restore_hp:
        sheet = await load_sheet(db, character)
        if "max_hp" in sheet.stats:
            mx = sheet.resolve("max_hp")
            hp, temp = await db.get_character_state(character.id)
            if hp is not None and (hp != mx or temp):
                changes.append(f"HP {hp}→{mx}")
            await db.set_character_state(character.id, mx, 0)
    return changes
