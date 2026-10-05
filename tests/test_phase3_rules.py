import asyncio
from collections import Counter

import pytest

from core.helpers import UserError
from core.progress import XP_PRESETS, level_for, parse_xp_table, xp_progress
from core.randtables import BUILTIN, format_entries, parse_entries, roll_on
from dice.engine import DiceError
from core.transfer import validate_payload


# ---------------------------------------------------------------- random tables

def test_parse_entries():
    e = parse_entries("3* wolves; a merchant ;  ;2*  bandits")
    assert e == [[3, "wolves"], [1, "a merchant"], [2, "bandits"]]
    assert parse_entries("one\ntwo; still two") == [[1, "one"], [1, "two; still two"]]  # newlines win over ;
    assert parse_entries(format_entries(e)) == e
    for bad in ["", " ; ", "0* nope", "[[1d]] broken roll", "x" * 400]:
        with pytest.raises(DiceError):
            parse_entries(bad)


def roll_sync(entries, tables=None):
    tables = tables or {}

    async def resolve(name):
        return tables.get(name) or BUILTIN.get(name)
    return asyncio.run(roll_on(entries, resolve))


def test_weights_are_respected():
    counts = Counter(roll_sync([[9, "common"], [1, "rare"]]) for _ in range(2000))
    assert counts["common"] > counts["rare"] * 4


def test_inline_rolls_and_nesting():
    for _ in range(50):
        r = roll_sync([[1, "[[2d6]] coins"]])
        assert 2 <= int(r.split()[0]) <= 12
    r = roll_sync([[1, "a {color} {animal}"]], {"color": [[1, "red"]], "animal": [[1, "fox"]]})
    assert r == "a red fox"
    assert roll_sync([[1, "{nope}"]]) == "{nope?}"
    # self-reference stops at the depth limit instead of looping forever
    r = roll_sync([[1, "x{loop}"]], {"loop": [[1, "x{loop}"]]})
    assert r.startswith("xxxxx") and r.endswith("loop")


def test_builtins_all_roll():
    for name in BUILTIN:
        for _ in range(20):
            out = roll_sync([[1, "{" + name + "}"]])
            assert "?}" not in out and "{" not in out, (name, out)


# ---------------------------------------------------------------- XP

def test_xp_tables():
    assert parse_xp_table("dnd5e") == XP_PRESETS["dnd5e"]
    assert parse_xp_table("none") is None
    assert parse_xp_table("1000, 3000 6000") == [0, 1000, 3000, 6000]
    for bad in ["0, 500, 400", "abc"]:
        with pytest.raises(UserError):
            parse_xp_table(bad)
    t = XP_PRESETS["dnd5e"]
    assert level_for(0, t) == 1 and level_for(299, t) == 1 and level_for(300, t) == 2
    assert level_for(10**9, t) == 20
    assert "to level 2" in xp_progress(150, t) and "(max)" in xp_progress(10**9, t)
    assert xp_progress(50, None) == "50 XP"


# ---------------------------------------------------------------- import validation

GOOD = {
    "dicebot_character": 1, "name": "Lyra", "avatar_url": None,
    "stats": {"dex": "4", "level": 3, "max_hp": "10+@level"},
    "skills": [{"name": "stealth", "kind": "formula", "formula": "1d20+@dex"},
               {"name": "climb", "kind": "3d20", "attributes": ["mu", "ge", "kk"], "points": 6}],
    "resources": [{"name": "slots_1", "current": 2, "max": 3, "reset": "long"}],
    "hp": 12, "temp_hp": 0, "xp": 900,
    "companions": [{"name": "Whiskers", "stats": {"hp": "3"}}],
}


def test_validate_good():
    clean = validate_payload(GOOD)
    assert clean["stats"]["level"] == "3" and clean["resources"][0][2] == "3"
    assert clean["companions"][0]["name"] == "Whiskers"


@pytest.mark.parametrize("patch", [
    {"dicebot_character": 99},
    {"name": ""},
    {"name": "Discord Dan"},
    {"stats": {"d20": "1"}},
    {"stats": {"dex": ["4"]}},
    {"skills": [{"name": "x", "kind": "magic"}]},
    {"skills": [{"name": "c", "kind": "3d20", "attributes": ["a", "b"], "points": 3}]},
    {"resources": [{"name": "ki", "current": -1, "max": "3"}]},
    {"resources": [{"name": "ki", "current": 1, "max": "3", "reset": "daily"}]},
    {"xp": "lots"},
    {"hp": True},
    {"avatar_url": "javascript:alert(1)"},
    {"companions": [{"name": "A"}] * 11},
])
def test_validate_rejects(patch):
    with pytest.raises(UserError):
        validate_payload({**GOOD, **patch})
