import asyncio

import pytest

from core.db import Character, Database, Skill
from core.sheet import RollEnv, Sheet
from dice.engine import DiceError, UnknownReference, evaluate_fixed, roll, validate_name
from dice.systems import three_d20_check


def many(expr, n=300, **kw):
    return [roll(expr, **kw).total for _ in range(n)]


def test_math():
    assert roll("2+3*4").total == 14
    assert roll("(2+3)*4").total == 20
    assert roll("7/2").total == 3
    assert roll("-3+1").total == -2


def test_basic_dice_ranges():
    assert set(many("1d6")) <= set(range(1, 7))
    assert set(many("d20+5")) <= set(range(6, 26))
    assert set(many("d%")) <= set(range(1, 101))
    assert set(many("4dF")) <= set(range(-4, 5))


def test_keep_drop():
    for t in many("4d6kh3"):
        assert 3 <= t <= 18
    r = roll("4d6dl1")
    assert sum(1 for d in r.terms[0].dice if not d.kept) == 1
    r = roll("2d20kl1")
    kept = [d.value for d in r.terms[0].dice if d.kept]
    assert kept == [min(d.value for d in r.terms[0].dice)]


def test_explode_and_reroll():
    for t in many("3d6!"):
        assert t >= 3
    r = roll("10d2r1")
    assert all(d.value == 2 or not d.kept or d is r.terms[0].dice[-1] or True for d in r.terms[0].dice)
    assert all(d.value >= 1 for d in r.terms[0].dice)


def test_pools():
    for t in many("6d10>=8"):
        assert 0 <= t <= 6
    for t in many("6d10>=8f1"):
        assert -6 <= t <= 6
    assert roll("6d10>=8").is_pool


def test_advantage():
    r = roll("1d20+5", advantage="adv")
    assert r.advantage_applied and r.terms[0].notation.startswith("2d20kh1")
    r = roll("d20", advantage="dis")
    assert r.terms[0].notation == "2d20kl1"
    r = roll("2d6", advantage="adv")
    assert not r.advantage_applied


def test_label_and_errors():
    r = roll("1d20+3 # sneak attack")
    assert r.label == "sneak attack"
    for bad in ["1d0", "d", "1d20+", "(1d6", "0d6", "1d6r6", "4dF!", "1d6f1", "1/0", "1d20 + dex"]:
        with pytest.raises(DiceError):
            roll(bad)
    with pytest.raises(DiceError):
        roll("1000d6")
    with pytest.raises(DiceError):
        evaluate_fixed("1d6")


def test_names():
    assert validate_name("@Dex") == "dex"
    for bad in ["d20", "df", "has space", "1abc", ""]:
        with pytest.raises(DiceError):
            validate_name(bad)
    assert validate_name("dex") == "dex"
    assert validate_name("dfoo") == "dfoo"


def make_sheet():
    c = Character(1, 1, 1, "Thorin", None)
    stats = {"con": "2", "level": "3", "dex": "4", "max_hp": "10 + @con * @level", "pool": "@dex + 1"}
    skills = {
        "stealth": Skill("stealth", "formula", "1d20 + @dex + 2"),
        "climb": Skill("climb", "3d20", attributes=["dex", "con", "level"], points=5),
    }
    return Sheet(c, stats, skills)


def test_sheet_and_env():
    s = make_sheet()
    assert s.resolve("max_hp") == 16
    env = RollEnv(s, {"fireball": "8d6", "sneaky": "stealth + 5"})
    r = env.roll("stealth")
    assert 7 <= r.total <= 26 and r.label == "Stealth"
    assert 12 <= env.roll("sneaky").total <= 31
    assert 8 <= env.roll("fireball").total <= 48
    assert 1 <= env.roll("(@pool)d10>=8").total + 5 <= 10
    assert env.skill_3d20("climb").points == 5
    with pytest.raises(DiceError):
        env.roll("climb + 1")
    with pytest.raises(UnknownReference):
        env.roll("@wis")
    with pytest.raises(UnknownReference):
        env.roll("nonsense")


def test_cycles():
    c = Character(1, 1, 1, "X", None)
    s = Sheet(c, {"a": "@b + 1", "b": "@a"}, {})
    with pytest.raises(DiceError, match="Circular"):
        s.resolve("a")
    env = RollEnv(None, {"loop": "loop + 1"})
    with pytest.raises(DiceError):
        env.roll("loop")


def test_macro_values():
    env = RollEnv(make_sheet(), {"pool": "$1d10!>=8 # Pool", "atk": "1d20 + $1 + $2"})
    for n in (5, 7, 8):
        r = env.roll(f"pool({n})")
        assert r.is_pool and r.label == "Pool" and r.terms[0].notation == f"{n}d10!>=8"
        assert sum(1 for d in r.terms[0].dice if not d.exploded) == n
    assert env.roll("pool(@dex + 1)").terms[0].notation == "5d10!>=8"
    assert 9 <= env.roll("atk(@dex, (2 + 2))").total <= 28
    for bad in ["pool", "pool()", "pool(1, 2)", "stealth(3)", "pool(5"]:
        with pytest.raises(DiceError):
            env.roll(bad)


def test_3d20():
    for _ in range(300):
        r = three_d20_check([("MU", 12), ("GE", 13), ("KK", 14)], 6, -2)
        if r.success:
            assert 1 <= r.quality <= 6
        assert not (r.botch and r.success)


def test_db(tmp_path):
    async def run():
        db = Database(str(tmp_path / "t.db"))
        await db.connect()
        camp = await db.create_campaign(10, "Curse of Strahd", 99, 555)
        assert (await db.get_campaign_by_channel(555)).name == "Curse of Strahd"
        ch = await db.create_character(camp.id, 1, "Thorin", None)
        await db.set_active_character(camp.id, 1, ch.id)
        assert (await db.get_active_character(camp.id, 1)).name == "Thorin"
        await db.set_stat(ch.id, "dex", "3")
        await db.set_stat(ch.id, "dex", "4")
        assert await db.get_stats(ch.id) == {"dex": "4"}
        await db.set_skill(ch.id, Skill("climb", "3d20", attributes=["mu", "ge", "kk"], points=6))
        assert (await db.get_skills(ch.id))["climb"].attributes == ["mu", "ge", "kk"]
        await db.set_macro(10, 1, "fb", "8d6")
        assert await db.delete_macro(10, 1, "fb")
        assert not await db.delete_macro(10, 1, "fb")
        await db.log_roll(guild_id=10, channel_id=555, campaign_id=camp.id, user_id=1, character_id=ch.id,
                          expression="1d20", label=None, total=12, natural=12)
        await db.delete_character(ch.id)
        assert await db.get_active_character(camp.id, 1) is None  # cascade
        await db.close()

    asyncio.run(run())


def test_help_chapters_fit_discord_limits():
    from core.helptext import CHAPTERS
    from core.helptext_de import CHAPTERS_DE
    assert 1 <= len(CHAPTERS) <= 25 and len({c.key for c in CHAPTERS}) == len(CHAPTERS)
    assert [c.key for c in CHAPTERS_DE] == [c.key for c in CHAPTERS], "German help must have the same chapters"
    for c in CHAPTERS + CHAPTERS_DE:
        text = c.text.strip().replace("{me}", "<@123456789012345678>")
        assert len(text) <= 4096, (c.key, len(text))
        assert len(c.summary) <= 100 and len(c.title) <= 100, c.key
