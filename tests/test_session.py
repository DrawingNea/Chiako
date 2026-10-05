"""
End-to-end: a simulated game session through the real cogs and a real SQLite database.
Run `python -m tests.test_session` to print the whole transcript.
"""
import asyncio
import re
import types

from discord.app_commands import Choice

from cogs.campaigns import Campaigns
from cogs.characters import Characters
from cogs.rolling import Rolling
from core.db import Database
from tests.fake_discord import (
    FakeChannel, FakeGuild, FakeInteraction, FakeMessage, FakeUser, FakeWebhook, Recorder, invoke, press,
)

VERBOSE = False


async def run_session(db_path: str):
    db = Database(db_path)
    await db.connect()
    try:
        await _session(db)
    finally:
        await db.close()


async def _session(db):
    rec = Recorder()
    bot = types.SimpleNamespace(db=db, user=types.SimpleNamespace(id=1))
    camp, chars, rolls = Campaigns(bot), Characters(bot), Rolling(bot)

    gm = FakeUser(rec, 100, "GameMaster")
    anna = FakeUser(rec, 200, "Anna")
    ben = FakeUser(rec, 300, "Ben")
    guild = FakeGuild(1, [gm, anna, ben])
    table = FakeChannel(rec, 50)
    other = FakeChannel(rec, 60)

    def as_(user, channel=table):
        return FakeInteraction(rec, user, guild, channel)

    step_no = 0

    async def step(title, coro, expect=None, where=None):
        nonlocal step_no
        step_no += 1
        before = len(rec.log)
        await coro
        new = rec.log[before:]
        assert new, f"{title}: bot sent nothing"
        out = "\n".join(f"  ({s.where}) " + s.text().replace("\n", "\n  ") for s in new)
        if VERBOSE:
            print(f"\n── {step_no}. {title}\n{out}")
        if expect:
            assert re.search(expect, out, re.S), f"{title}: expected /{expect}/ in:\n{out}"
        if where:
            assert any(s.where == where for s in new), f"{title}: expected a '{where}' message, got {[s.where for s in new]}"
        return new

    # ---------------------------------------------------------------- campaign setup
    await step("Anna rolls before any campaign exists (plain dice still work)",
               invoke(rolls.r, rolls, as_(anna), expression="2d6+3"), r"# \d+")
    await step("Anna tries /char create without a campaign",
               invoke(chars.char_create, chars, as_(anna), name="Lyra"), "isn't part of a campaign", "ephemeral")
    await step("GM creates the campaign",
               invoke(camp.create, camp, as_(gm), name="Curse of Strahd"), "Campaign created")
    await step("GM tries to create a second campaign in the same channel",
               invoke(camp.create, camp, as_(gm), name="Other"), "already belongs")
    await step("Ben (not GM) tries to link another channel",
               invoke(camp.link, camp, as_(ben, other), name="Curse of Strahd"), "Only the GM")
    await step("GM links a second channel",
               invoke(camp.link, camp, as_(gm, other), name="Curse of Strahd"), "now belongs")

    # ---------------------------------------------------------------- characters
    await step("Anna creates Lyra",
               invoke(chars.char_create, chars, as_(anna), name="Lyra", avatar_url="https://img.example/lyra.png"),
               "Lyra.*active")
    await step("Duplicate name is rejected",
               invoke(chars.char_create, chars, as_(anna), name="lyra"), "already have")
    await step("Webhook-forbidden name is rejected",
               invoke(chars.char_create, chars, as_(anna), name="Clyde the Bold"), "clyde")
    await step("Bad avatar URL is rejected",
               invoke(chars.char_avatar, chars, as_(anna), url="not a url"), "https://")
    await step("Anna sets stats in bulk, incl. a derived stat",
               invoke(chars.stat_bulk, chars, as_(anna),
                      entries="str=1, dex=4, con=2, level=3, prof=2, max_hp=10+@con*@level"),
               r"max_hp` = \*\*16")
    await step("Derived stat referencing a missing stat warns but saves",
               invoke(chars.stat_set, chars, as_(anna), name="ac", value="10+@dex+@shield"), "no stat `shield`")
    await step("…and works once the stat exists",
               invoke(chars.stat_set, chars, as_(anna), name="shield", value="2"), r"shield` = \*\*2")
    await step("Circular formula is rejected",
               invoke(chars.stat_set, chars, as_(anna), name="shield", value="@ac"), "Circular")
    await step("Dice in a stat are rejected",
               invoke(chars.stat_set, chars, as_(anna), name="luck", value="1d6"), "Dice aren't allowed")
    await step("Invalid stat name is rejected",
               invoke(chars.stat_set, chars, as_(anna), name="d20", value="1"), "looks like dice")
    await step("Anna adds a formula skill",
               invoke(chars.skill_add, chars, as_(anna), name="stealth", formula="1d20+@dex+@prof"), "learned `stealth`")
    await step("Skill with a syntax error is rejected",
               invoke(chars.skill_add, chars, as_(anna), name="broken", formula="1d20+(@dex"), "Missing")
    await step("Anna adds a 3d20 skill",
               invoke(chars.skill_add_3d20, chars, as_(anna), name="climb", attr1="dex", attr2="con",
                      attr3="str", points=8), "3d20 vs dex/con/str")
    await step("Anna saves a macro with a label",
               invoke(chars.macro_save, chars, as_(anna), name="fireball", expression="8d6 # Fireball!"), "saved")
    await step("Character sheet",
               invoke(chars.char_show, chars, as_(anna)), r"`Max HP\s*` \*\*16\*\*.*Skills: .*`Stealth\s*` `1d20\+@dex\+@prof`")
    await step("Ben creates two characters and switches",
               invoke(chars.char_create, chars, as_(ben), name="Grom"), "Grom")
    await invoke(chars.char_create, chars, as_(ben), name="Pip")
    await step("Ben's list shows Pip active",
               invoke(chars.char_list, chars, as_(ben)), "Pip")
    await step("Ben switches back to Grom",
               invoke(chars.char_use, chars, as_(ben), name="grom"), "now playing \\*\\*Grom")

    # ---------------------------------------------------------------- rolling
    await step("/r stealth (skill, posted as Lyra)",
               invoke(rolls.r, rolls, as_(anna), expression="stealth"),
               r"Results for Lyra.*Stealth\*\* · 1 × 20-sided die \+ dex\(4\) \+ prof\(2\)\n\s*## `\d+`\n\s*# \d+")
    await step("/r stealth+2 with advantage",
               invoke(rolls.r, rolls, as_(anna), expression="stealth+2",
                      advantage=Choice(name="Advantage", value="adv")), r"1 × 20-sided die with advantage \+ dex")
    await step("/r fireball (macro label)",
               invoke(rolls.r, rolls, as_(anna), expression="fireball"), r"Fireball!\*\* · 8 × 6-sided dice")
    await step("/check climb with a -2 modifier (3d20)",
               invoke(rolls.check, rolls, as_(anna), skill="climb", modifier=-2),
               r"DEX\*\* 2 → .*CON\*\* 0 → .*STR\*\* -1 → ")
    await step("/check unknown skill",
               invoke(rolls.check, rolls, as_(anna), skill="swim"), "no skill `swim`")
    await step("/r using a 3d20 skill in math is explained",
               invoke(rolls.r, rolls, as_(anna), expression="climb+1"), "3d20 check")
    await step("/r with stat Ben doesn't have",
               invoke(rolls.r, rolls, as_(ben), expression="1d20+@dex"), "Grom.*no stat `dex`")
    await step("Stats work without @ (no accidental Discord mentions)",
               invoke(rolls.r, rolls, as_(anna), expression="1d20+dex"), r"1 × 20-sided die \+ dex\(4\)")
    await step("Unknown names say what's missing",
               invoke(rolls.r, rolls, as_(anna), expression="1d20+wis"),
               r"Lyra\*\* has no stat, skill or macro called `wis`")
    await step("Dice pool from stats",
               invoke(rolls.r, rolls, as_(anna), expression="(@dex+@prof)d10>=8 # Pool test"),
               r"Results for Lyra.*Pool test\*\* · 6 × 10-sided dice · success at ≥ 8\n\s*## .*`\d+`.*\n\s*# (\d+ Success|No successes)")
    await step("Fate dice", invoke(rolls.r, rolls, as_(anna), expression="4dF+@prof"), r"# [+-]\d+ · \w+")
    await step("/pbta", invoke(rolls.pbta, rolls, as_(anna), modifier="@prof", label="Act under fire"),
               r"Act under fire.*(Strong hit|Weak hit|Miss)")
    await step("/3d20 raw", invoke(rolls.three_d20, rolls, as_(ben), attr1=12, attr2=13, attr3=14, points=5),
               r"(Success|Failed|Critical|Botch)")
    await step("Rolls in a thread-less linked channel use the same campaign",
               invoke(rolls.r, rolls, as_(anna, other), expression="stealth"), r"Results for Lyra")

    # ---------------------------------------------------------------- buttons
    new = await step("Anna rolls…", invoke(rolls.r, rolls, as_(anna), expression="1d20+@dex"))
    view = new[-1].view
    await step("…Ben can't press her reroll button",
               press(view.reroll, as_(ben)), "Only the person who rolled", "ephemeral")
    await step("…Anna can", press(view.reroll, as_(anna)), r"Results for Lyra.*# \d+")

    # ---------------------------------------------------------------- secret rolls
    await step("Player secret roll goes to the GM's DMs",
               invoke(rolls.secret, rolls, as_(anna), expression="stealth"), r"Lyra\*\* made a secret roll")
    assert any(s.where == "dm:GameMaster" and "Stealth" in s.text() for s in rec.log), "GM didn't get the DM"
    new = await step("GM secret roll is private with a reveal button",
                     invoke(rolls.secret, rolls, as_(gm), expression="1d20+5 # Perception"), "Perception", "ephemeral")
    await step("GM reveals it", press(new[-1].view.reveal, as_(gm)), "Revealed", "reply")

    # ---------------------------------------------------------------- inline rolls
    async def say(user, text):
        await rolls.on_message(FakeMessage(rec, user, guild, table, text))

    await step("Inline rolls in chat: the sentence comes back with the results filled in",
               say(anna, "I sneak [[stealth]] and then cast [[fireball]]"),
               r"I sneak \*\*\d+\*\* and then cast \*\*\d+\*\*.*Stealth.*Fireball!")
    await step("One inline roll: the sentence replaces the card's result line",
               say(anna, "I make [[2d6+3]] backflips and pose!"),
               r"## `\d+` `\d+`\n\s*### I make \*\*\d+\*\* backflips and pose!")
    await step("Inline roll with an error",
               say(anna, "oops [[1d20+]]"), "")
    before = len(rec.log)
    await say(anna, "no rolls here [just brackets]")
    assert len(rec.log) == before, "bot replied to a normal message"

    # ---------------------------------------------------------------- webhooks
    hook = FakeWebhook(rec)

    async def fake_get(channel):
        return hook, None

    rolls.hooks.get = fake_get
    await step("With webhooks, the roll is posted as the character",
               invoke(rolls.r, rolls, as_(anna), expression="stealth"), r"Stealth", "webhook:Lyra")
    await step("Without a character, no webhook is used",
               invoke(rolls.r, rolls, as_(gm), expression="1d20"), r"# \d+", "reply")
    await step("GM disables webhooks", invoke(camp.webhooks, camp, as_(gm), enabled=False), "disabled")
    await step("…now it's a normal bot post", invoke(rolls.r, rolls, as_(anna), expression="stealth"),
               r"Results for Lyra", "reply")

    # ---------------------------------------------------------------- campaign info & cleanup
    await step("Campaign info", invoke(camp.info, camp, as_(ben)), r"Lyra.*Grom, Pip|Grom, Pip.*Lyra")
    await step("GM role (by non-GM)", invoke(camp.gm_role, camp, as_(ben)), "Only the GM")
    new = await step("Ben deletes Pip (confirm dialog)", invoke(chars.char_delete, chars, as_(ben), name="Pip"),
                     "Really delete")
    await step("Anna can't confirm Ben's delete", press(new[-1].view.confirm, as_(anna)), "Not your character")
    await step("Ben confirms", press(new[-1].view.confirm, as_(ben)), "deleted")
    await step("Macro list", invoke(chars.macro_list, chars, as_(anna)), "fireball")

    # ---------------------------------------------------------------- campaign macros
    await step("Ben (not GM) can't save a campaign macro",
               invoke(chars.macro_save, chars, as_(ben), name="pool", expression="$1d10!>=8", campaign=True),
               "Only the GM")
    await step("GM saves a campaign macro for everyone",
               invoke(chars.macro_save, chars, as_(gm), name="pool", expression="$1d10!>=8 # Pool", campaign=True),
               r"Campaign macro `pool` saved.*/r pool\(5\)", "reply")
    await step("Ben rolls the GM's macro", invoke(rolls.r, rolls, as_(ben), expression="pool(3)"),
               r"Results for Grom.*Pool\*\* · 3 × 10-sided dice · success at ≥ 8 · 10s explode")
    await invoke(chars.macro_save, chars, as_(anna), name="pool", expression="$1d6>=5 # My pool")
    await step("Anna's own macro with the same name wins", invoke(rolls.r, rolls, as_(anna), expression="pool(2)"),
               r"My pool\*\* · 2 × 6-sided dice · success at ≥ 5")
    await step("Macro list shows both, and the override",
               invoke(chars.macro_list, chars, as_(anna)), r"Campaign: Curse of Strahd.*overrides it.*Yours")
    await step("GM removes the campaign macro",
               invoke(chars.macro_remove, chars, as_(gm), name="pool", campaign=True), "Campaign macro `pool` deleted")
    await step("…so Ben can't roll it any more", invoke(rolls.r, rolls, as_(ben), expression="pool(3)"),
               "no stat, skill or macro called `pool`")

    # ---------------------------------------------------------------- campaign dice rules & talking to the bot
    await step("'@bot w5' without dice rules explains itself", say(anna, "<@1> w5"), "campaign's dice rules")
    await step("Ben (not GM) can't set dice rules",
               invoke(camp.dice, camp, as_(ben), sides=10, success=8), "Only the GM")
    await step("Impossible rules are rejected",
               invoke(camp.dice, camp, as_(gm), sides=10, explode=1), "Exploding on 1\\+")
    await step("GM sets dice rules: d10, success at 8+, 10s explode",
               invoke(camp.dice, camp, as_(gm), sides=10, success=8, explode=10),
               r"d10 · success at ≥ 8 · 10s explode.*/check shooting")
    await step("Anyone can look at them", invoke(camp.dice, camp, as_(ben)), "success at ≥ 8")
    await step("A skill that's just a number", invoke(chars.skill_add, chars, as_(anna), name="shooting", formula="3"),
               "learned `shooting`")
    await step("/check shooting rolls 3 campaign dice",
               invoke(rolls.check, rolls, as_(anna), skill="shooting"), r"Lyra.*Shooting\*\* · 3 × 10-sided dice ·")
    await step("/check skill & stat with a modifier: 3 + dex 4 + 1",
               invoke(rolls.check, rolls, as_(anna), skill="shooting & dex", modifier=1),
               r"Shooting & Dex \+1\*\* · 8 × 10-sided dice ·")
    await step("Skills with dice in them still roll as written",
               invoke(rolls.check, rolls, as_(anna), skill="stealth"), r"Stealth.*dex\(4\) \+ prof\(2\)")
    await step("Talking to the bot: '@bot roll for shooting und dex'",
               say(anna, "<@1> roll for shooting und dex"), r"Shooting & Dex\*\* · 7 × 10-sided dice")
    await step("'@bot w5' rolls five campaign dice", say(anna, "<@1> w5"), r"5 × 10-sided dice")
    await step("'@bot 2d6+3' is a normal roll", say(anna, "<@1> 2d6+3"), r"# \d+")
    await step("'@bot help'", say(anna, "<@1> help"), "Talk to me to roll")
    before = len(rec.log)
    await say(anna, "thanks <@1>, see you")
    assert len(rec.log) == before, "bot answered a message that only mentions it in passing"
    await step("'@bot check 10'", say(anna, "<@1> check 10"), r"10 × 10-sided dice")
    await step("'@bot checke 20' (German-style verb)", say(anna, "<@1> checke 20"), r"20 × 10-sided dice")
    await step("An unknown word gets a clear error", say(anna, "<@1> blub 20"), "no stat, skill or macro called `blub`")
    await step("German: '@bot Würfle auf shooting und dex'",
               say(anna, "<@1> Würfle auf shooting und dex"), r"Shooting & Dex\*\* · 7 × 10-sided dice")
    await step("'@bot hilfe'", say(anna, "<@1> hilfe"), "Talk to me to roll")
    await step("GM turns the dice rules off", invoke(camp.dice, camp, as_(gm), sides=0), "rules are off")
    await step("'@bot roll 10' without dice rules explains itself", say(anna, "<@1> roll 10"), "campaign's dice rules")
    new = await step("/help opens the first chapter", invoke(rolls.help, rolls, as_(anna)),
                     r"Getting started.*Chapter 1 of", "ephemeral")
    help_view = new[-1].view
    await step("…Next goes to chapter 2", press(help_view.next_page, as_(anna)), r"Rolling dice.*Writing a roll")
    await press(help_view.back, as_(anna))
    await step("…Back from chapter 1 wraps around to the last one", press(help_view.back, as_(anna)),
               r"Campaign settings \(GM\)")
    await step("…the menu jumps to any chapter", help_view.show(as_(anna), "pools"), r"Dice pools.*campaign dice")

    # every roll was logged
    async with db.conn.execute("SELECT COUNT(*), SUM(secret) FROM roll_log") as cur:
        total, secret = await cur.fetchone()
    assert total == 32 and secret == 2, (total, secret)
    if VERBOSE:
        print(f"\n{step_no} steps passed, {total} rolls logged ({secret} secret)")


def test_session(tmp_path):
    asyncio.run(run_session(str(tmp_path / "session.db")))


if __name__ == "__main__":
    import tempfile
    VERBOSE = True
    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run_session(f"{d}/session.db"))
