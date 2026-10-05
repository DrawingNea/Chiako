"""Export characters (with companions) to JSON and import them again, with strict validation."""
from __future__ import annotations

import re
from typing import Optional

from dice.engine import DiceError, validate_name

from .db import Character, Database, Resource, Skill
from .helpers import UserError

FORMAT_KEY = "dicebot_character"
FORMAT_VERSION = 1
MAX_BYTES = 256 * 1024


async def export_character(db: Database, ch: Character, *, with_companions: bool = True) -> dict:
    hp, temp = await db.get_character_state(ch.id)
    data = {
        FORMAT_KEY: FORMAT_VERSION,
        "name": ch.name,
        "avatar_url": ch.avatar_url,
        "stats": await db.get_stats(ch.id),
        "skills": [
            {"name": s.name, "kind": s.kind, "formula": s.formula, "attributes": s.attributes, "points": s.points}
            for s in (await db.get_skills(ch.id)).values()
        ],
        "resources": [
            {"name": r.name, "current": r.current, "max": r.max_formula, "reset": r.reset}
            for r in (await db.get_resources(ch.id)).values()
        ],
        "hp": hp,
        "temp_hp": temp,
        "xp": await db.get_xp(ch.id),
        "color": ch.color,
        "items": [{"name": i.name, "qty": i.qty, "note": i.note}
                  for i in await db.list_items(ch.campaign_id, ch.id)],
        "money": await db.get_money(ch.campaign_id, ch.id),
    }
    if with_companions:
        data["companions"] = [await export_character(db, c, with_companions=False)
                              for c in await db.list_companions(ch.id)]
    return data


# --------------------------------------------------------------------------- validation

def _fail(msg: str):
    raise UserError(f"Import failed: {msg}")


def _int(value, what, lo=0, hi=10_000_000, optional=False) -> Optional[int]:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        _fail(f"{what} must be a whole number between {lo} and {hi}.")
    return value


def _str(value, what, max_len, optional=False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > max_len:
        _fail(f"{what} must be text of at most {max_len} characters.")
    return value


def _name(value, what) -> str:
    try:
        return validate_name(_str(value, what, 40), what)
    except DiceError as e:
        _fail(str(e))


def validate_payload(data, *, nested: bool = False) -> dict:
    """Check everything before anything is written. Returns a cleaned copy."""
    if not isinstance(data, dict):
        _fail("the file isn't a character export.")
    if not nested and data.get(FORMAT_KEY) != FORMAT_VERSION:
        _fail("this isn't a dice bot character file (or it's from a newer version).")

    out = {"name": " ".join(_str(data.get("name"), "name", 32).split())}
    if not out["name"]:
        _fail("the character has no name.")
    if re.search(r"discord|clyde", out["name"], re.I):
        _fail(f"Discord doesn't allow 'discord' or 'clyde' in names (`{out['name']}`). Use the `name` option.")
    avatar = _str(data.get("avatar_url"), "avatar_url", 500, optional=True)
    if avatar and not re.match(r"^https?://\S+$", avatar):
        _fail("avatar_url must be an http(s) link.")
    out["avatar_url"] = avatar

    stats = data.get("stats") or {}
    if not isinstance(stats, dict) or len(stats) > 200:
        _fail("stats must be a list of at most 200 name/value pairs.")
    out["stats"] = {}
    for k, v in stats.items():
        if isinstance(v, int) and not isinstance(v, bool):
            v = str(v)
        out["stats"][_name(k, "stat name")] = _str(v, f"stat `{k}`", 400)

    skills = data.get("skills") or []
    if not isinstance(skills, list) or len(skills) > 200:
        _fail("skills must be a list of at most 200 entries.")
    out["skills"] = []
    for s in skills:
        if not isinstance(s, dict):
            _fail("every skill must be an object.")
        name = _name(s.get("name"), "skill name")
        kind = s.get("kind", "formula")
        if kind == "formula":
            out["skills"].append(Skill(name, "formula", _str(s.get("formula"), f"skill `{name}`", 400)))
        elif kind == "3d20":
            attrs = s.get("attributes")
            if not isinstance(attrs, list) or len(attrs) != 3:
                _fail(f"3d20 skill `{name}` needs exactly 3 attributes.")
            out["skills"].append(Skill(name, "3d20", attributes=[_name(a, "attribute") for a in attrs],
                                       points=_int(s.get("points"), f"points of `{name}`", 0, 99)))
        else:
            _fail(f"unknown skill kind `{kind}`.")

    resources = data.get("resources") or []
    if not isinstance(resources, list) or len(resources) > 50:
        _fail("resources must be a list of at most 50 entries.")
    out["resources"] = []
    for r in resources:
        if not isinstance(r, dict):
            _fail("every resource must be an object.")
        name = _name(r.get("name"), "resource name")
        reset = r.get("reset", "long")
        if reset not in ("short", "long", "never"):
            _fail(f"resource `{name}` has an unknown reset `{reset}`.")
        mx = r.get("max")
        if isinstance(mx, int) and not isinstance(mx, bool):
            mx = str(mx)
        out["resources"].append((name, _int(r.get("current"), f"current of `{name}`", 0, 100000),
                                 _str(mx, f"max of `{name}`", 200), reset))

    out["hp"] = _int(data.get("hp"), "hp", 0, 1_000_000, optional=True)
    out["temp_hp"] = _int(data.get("temp_hp", 0), "temp_hp", 0, 1_000_000)
    out["xp"] = _int(data.get("xp", 0), "xp", 0, 1_000_000_000)
    out["color"] = _int(data.get("color"), "color", 0, 0xFFFFFF, optional=True)

    items = data.get("items") or []
    if not isinstance(items, list) or len(items) > 500:
        _fail("items must be a list of at most 500 entries.")
    out["items"] = []
    for i in items:
        if not isinstance(i, dict):
            _fail("every item must be an object.")
        name = " ".join(_str(i.get("name"), "item name", 100).split())
        if not name:
            _fail("an item has no name.")
        out["items"].append((name, _int(i.get("qty", 1), f"amount of `{name}`", 1, 1_000_000_000),
                             _str(i.get("note"), f"note of `{name}`", 300, optional=True)))

    money = data.get("money") or {}
    if not isinstance(money, dict) or len(money) > 20:
        _fail("money must be at most 20 currency/amount pairs.")
    out["money"] = {}
    for cur, amount in money.items():
        cur = " ".join(_str(cur, "currency", 32).split())
        if cur:
            out["money"][cur] = _int(amount, f"amount of `{cur}`", 0, 1_000_000_000_000)

    out["companions"] = []
    if not nested:
        comps = data.get("companions") or []
        if not isinstance(comps, list) or len(comps) > 10:
            _fail("companions must be a list of at most 10 entries.")
        out["companions"] = [validate_payload(c, nested=True) for c in comps]
    return out


async def import_character(db: Database, campaign_id: int, owner_id: int, data: dict,
                           name_override: Optional[str] = None) -> tuple[Character, list[Character]]:
    clean = validate_payload(data)
    if name_override:
        clean["name"] = name_override

    names = [clean["name"]] + [c["name"] for c in clean["companions"]]
    if len({n.lower() for n in names}) != len(names):
        _fail("a companion has the same name as another character in the file.")
    for n in names:
        if await db.get_character_by_name(campaign_id, owner_id, n):
            _fail(f"you already have a character called **{n}** here. Use the `name` option to rename it.")

    async def write(c: dict, parent_id: Optional[int]) -> Character:
        ch = await db.create_character(campaign_id, owner_id, c["name"], c["avatar_url"], parent_id)
        for k, v in c["stats"].items():
            await db.set_stat(ch.id, k, v)
        for s in c["skills"]:
            await db.set_skill(ch.id, s)
        for name, cur, mx, reset in c["resources"]:
            await db.set_resource(Resource(ch.id, name, cur, mx, reset))
        await db.set_character_state(ch.id, c["hp"], c["temp_hp"])
        await db.set_xp(ch.id, c["xp"])
        if c["color"] is not None:
            await db.update_character(ch.id, color=c["color"])
        for name, qty, note in c["items"]:
            await db.add_item(campaign_id, ch.id, name, qty, note)
        for cur, amount in c["money"].items():
            if amount:
                await db.change_money(campaign_id, ch.id, cur, amount)
        return await db.get_character(ch.id)

    main = await write(clean, None)
    companions = [await write(c, main.id) for c in clean["companions"]]
    return main, companions
