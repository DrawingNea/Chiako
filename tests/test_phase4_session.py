"""
End-to-end Phase 4: achievements, sessions & recaps, stats, hall of fame, scheduling and reminders.
Dice are rigged and the clock is controlled, so every number can be checked exactly.
Run `python -m tests.test_phase4_session` to print the transcript.
"""
import asyncio
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from discord.app_commands import Choice

import core.clock as clock
import dice.engine as engine
from cogs.campaigns import Campaigns
from cogs.characters import Characters
from cogs.combat import Combat
from cogs.companions import Companions
from cogs.groupcheck import GroupCheck
from cogs.health import Health
from cogs.lore import Lore
from cogs.progress import Progress
from cogs.rolling import Rolling
from cogs.schedule import Scheduling
from cogs.sessions import Sessions
from core.db import Database
from tests.fake_discord import FakeBot, FakeChannel, FakeGuild, FakeInteraction, FakeUser, Recorder, invoke

VERBOSE = False
BERLIN = ZoneInfo("Europe/Berlin")
START = int(datetime(2026, 10, 4, 20, 0, tzinfo=BERLIN).timestamp())  # Sunday evening


def berlin(*a) -> int:
    return int(datetime(*a, tzinfo=BERLIN).timestamp())


class Rigged:
    """Stands in for the dice RNG: hands out queued values first, then real random ones."""

    def __init__(self):
        self.queue, self.real = [], random.SystemRandom()

    def randint(self, a, b):
        return self.queue.pop(0) if self.queue else self.real.randint(a, b)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, seconds=30):
        self.t += seconds


async def run(db_path: str):
    real_now, real_rng = clock.now, engine._rng
    clk, dice = Clock(START), Rigged()
    clock.now, engine._rng = clk, dice
    db = Database(db_path)
    await db.connect()
    try:
        await _session(db, clk, dice)
    finally:
        await db.close()
        clock.now, engine._rng = real_now, real_rng


async def _session(db, clk: Clock, dice: Rigged):
    rec = Recorder()
    table = FakeChannel(rec, 50)
    bot = FakeBot(db, [table])
    bot.enable_achievements()
    for cls in (Campaigns, Characters, Rolling, Combat, Health, GroupCheck, Progress, Companions, Lore, Sessions,
                Scheduling):
        await bot.add_cog(cls(bot))
    g = bot.get_cog
    camp, chars, rolling, combat, health, prog, comp, lore, sess, sched = (
        g(n) for n in ("Campaigns", "Characters", "Rolling", "Combat", "Health", "Progress", "Companions", "Lore",
                       "Sessions", "Scheduling"))
    gm, anna, ben = FakeUser(rec, 100, "GameMaster"), FakeUser(rec, 200, "Anna"), FakeUser(rec, 300, "Ben")
    guild = FakeGuild(1, [gm, anna, ben])

    def as_(user, message=None):
        i = FakeInteraction(rec, user, guild, table, message)
        i.client = bot
        return i

    n = 0

    async def step(title, coro, expect=None, where=None, absent=None):
        nonlocal n
        n += 1
        clk.tick()
        before = len(rec.log)
        await coro
        new = rec.log[before:]
        assert new, f"{title}: bot sent nothing"
        out = "\n".join(f"  ({s.where}) " + s.text().replace("\n", "\n  ") for s in new
                        if not s.where.startswith("edit#"))
        if VERBOSE:
            print(f"\n── {n}. {title}\n{out}")
        if expect:
            assert re.search(expect, out, re.S), f"{title}: expected /{expect}/ in:\n{out}"
        if where:
            assert any(s.where.startswith(where) for s in new), f"{title}: no '{where}' in {[s.where for s in new]}"
        if absent:
            assert not re.search(absent, out, re.S), f"{title}: /{absent}/ must not appear in:\n{out}"
        return new

    async def r(user, expr, *rigged):
        dice.queue += list(rigged)
        clk.tick()
        await invoke(rolling.r, rolling, as_(user), expression=expr)

    # ---------------------------------------------------------------- setup
    await invoke(camp.create, camp, as_(gm), name="Strahd")
    await step("Unknown time zone", invoke(camp.timezone, camp, as_(gm), name="Mars/Olympus"), "Unknown time zone")
    await step("GM sets the time zone (any capitalisation)",
               invoke(camp.timezone, camp, as_(gm), name="europe/berlin"), r"Time zone set to \*\*Europe/Berlin\*\*")
    assert (await db.get_campaign(1)).timezone == "Europe/Berlin"
    await invoke(chars.char_create, chars, as_(anna), name="Lyra")
    await invoke(chars.stat_bulk, chars, as_(anna), entries="max_hp=20, level=1")
    await invoke(chars.char_create, chars, as_(ben), name="Grom")
    await invoke(chars.stat_bulk, chars, as_(ben), entries="max_hp=30, level=1")

    # ---------------------------------------------------------------- achievements from rolls
    dice.queue.append(10)
    await step("First roll ever", invoke(rolling.r, rolling, as_(anna), expression="1d20"),
               r"Achievement unlocked.*<@200> earned \*\*Let's Roll", "channel")
    dice.queue.append(20)
    await step("A natural 20", invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"Natural Talent")
    dice.queue.append(20)
    await step("Two in a row", invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"Lightning Strikes Twice",
               absent="Natural Talent")
    dice.queue.append(1)
    await step("A natural 1", invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"Critical Failure")
    dice.queue.append(1)
    await step("Second 1: nothing new", invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"# 1\b",
               absent="Achievement")
    dice.queue.append(1)
    await step("Three 1s in a row", invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"Cursed Dice")
    dice.queue += [6] * 10
    await step("A huge roll", invoke(rolling.r, rolling, as_(anna), expression="10d6+20 # Meteor"),
               r"# 80.*Overkill")
    dice.queue.append(20)
    await step("Ben's secret natural 20 earns nothing (it would give the secret away)",
               invoke(rolling.secret, rolling, as_(ben), expression="1d20"), "secret roll", absent="Achievement")
    assert await db.unlocked_achievements(1, 300) == {}

    # ---------------------------------------------------------------- session 1
    await step("Players can't start sessions", invoke(sess.start, sess, as_(anna)), "Only the GM")
    await step("GM starts session 1", invoke(sess.start, sess, as_(gm), title="The Goblin Cave"),
               r"Session 1\*\* begins: \*The Goblin Cave")
    await step("…only one at a time", invoke(sess.start, sess, as_(gm)), "already running")
    for v in (18, 19, 20):
        await r(anna, "1d20", v)
    for v in (2, 3, 4):
        await r(ben, "1d20", v)
    dice.queue.append(20)
    await invoke(rolling.secret, rolling, as_(ben), expression="1d20 # sneaky")
    await step("A memorable moment", invoke(sess.moment, sess, as_(ben), text="Grom tried to seduce the dragon"),
               "Noted", absent="won't be in a recap")

    await invoke(combat.monster_save, combat, as_(gm), name="Goblin", hp="7")
    await invoke(combat.start, combat, as_(gm))
    await invoke(combat.spawn, combat, as_(gm), template="Goblin")
    await step("Lyra slays the goblin", invoke(health.damage, health, as_(anna), amount="10", target="Goblin"),
               r"defeated.*First Blood")
    await step("Grom goes down", invoke(health.damage, health, as_(gm), amount="100", target="Grom"),
               r"drops to 0 HP", absent="Achievement")
    await step("Lyra heals him: Ben gets an achievement",
               invoke(health.heal, health, as_(anna), amount="5", target="Grom"),
               r"back on their feet.*<@300> earned \*\*Back from the Brink")
    await invoke(prog.xp_table, prog, as_(gm), thresholds="dnd5e")
    await step("Level 5 for both", invoke(prog.xp_award, prog, as_(gm), amount=6500, reason="the cave"),
               r"reached \*\*level 5.*Seasoned Adventurer.*Seasoned Adventurer")
    await invoke(combat.end, combat, as_(gm))

    clk.tick(3 * 3600)
    out = await step("GM ends the session: recap", invoke(sess.end, sess, as_(gm)),
                     r"Session 1: The Goblin Cave.*3h 0\dm.*6 rolls · 6 dice · 1 natural 20 · 0 natural 1s"
                     r".*Luckiest: <@200> \(dice \+89\.5% vs\. average\).*Unluckiest: <@300> \(dice -78\.9% vs\. average\)"
                     r".*Biggest roll: \*\*20\*\* by <@200>.*Most crits: <@200> \(1\)", absent="sneaky")
    recap = out[0].text()
    for moment in ["A fight broke out", "Lyra rolled a natural 20", "Grom tried to seduce the dragon (Grom)",
                   "Goblin was defeated", "Grom dropped to 0 HP", "Grom got back up", "Lyra reached level 5",
                   "Grom reached level 5", "The fight ended", "13,000 XP in total"]:
        assert moment in recap, f"recap is missing '{moment}':\n{recap}"
    assert recap.index("A fight broke out") < recap.index("Goblin was defeated") < recap.index("The fight ended")
    await step("Moments outside a session are flagged",
               invoke(sess.moment, sess, as_(anna), text="Afterparty"), "won't be in a recap")
    await step("Recap again later", invoke(sess.recap, sess, as_(ben)), r"Session 1: The Goblin Cave", "ephemeral")
    await step("Unknown session number", invoke(sess.recap, sess, as_(ben), number=7), "no session 7")

    # ---------------------------------------------------------------- sessions 2–5: the 'Regular' achievement
    for i in range(2, 5):
        clk.tick(86400)
        await invoke(sess.start, sess, as_(gm))
        await r(anna, "1d20", 10)
        clk.tick(3600)
        await invoke(sess.end, sess, as_(gm))
    clk.tick(86400)
    await invoke(sess.start, sess, as_(gm))
    dice.queue.append(10)
    await step("Anna's first roll in her fifth session: Regular",
               invoke(rolling.r, rolling, as_(anna), expression="1d20"), r"<@200> earned \*\*Regular")
    clk.tick(3600)
    await step("Session 5 recap", invoke(sess.end, sess, as_(gm)), r"Session 5.*1 roll · 1 die", absent="Regular")
    await step("Session list", invoke(sess.list_cmd, sess, as_(ben)), r"\*\*5\.\*\* \*untitled\*.*\*\*1\.\*\* The Goblin Cave")

    # ---------------------------------------------------------------- notes & companion achievements
    for i in range(4):
        await invoke(lore.note_add, lore, as_(anna), title=f"Note {i}", text="x")
    await step("Fifth note: Loremaster", invoke(lore.note_add, lore, as_(anna), title="Note 4", text="x"),
               "Loremaster")
    await step("Companion: Best Friend", invoke(comp.add, comp, as_(anna), name="Whiskers"), "Best Friend")

    # ---------------------------------------------------------------- stats & hall of fame
    await step("Anna's stats for the campaign", invoke(sess.stats, sess, as_(anna)),
               r"\*\*14\*\* rolls · \*\*23\*\* dice.*Blessed by the dice gods.*d20 · 13 dice: Ø \*\*11\.54\*\* · expected 10\.5"
               r".*20s: 3× \(23\.1%\) · 1s: 3× \(23\.1%\).*d6 · 10 dice.*\*\*80\*\* · Meteor.*20 │█+ +3", absent="sneaky")
    await step("Stats for the last session only", invoke(sess.stats, sess, as_(anna),
                                                          scope=Choice(name="s", value="session")),
               r"session 5.*\*\*1\*\* roll · \*\*1\*\* die")
    await step("Ben: not enough d20 rolls to judge", invoke(sess.stats, sess, as_(anna), player=ben),
               r"\*\*3\*\* rolls.*Not enough dice yet to judge your luck \(3/20\)", absent="sneaky")
    await step("Hall of Fame", invoke(sess.halloffame, sess, as_(ben)),
               r"Most natural 20s.*<@200> · 3.*Luckiest.*<@200> · \+49\.7%.*Unluckiest: —.*Biggest rolls.*<@200> · \*\*80\*\* \(Meteor\)"
               r".*Monster slayers.*<@200> · 1.*Achievements.*<@200>")
    out = await step("Achievement list", invoke(sess.achievements, sess, as_(ben), player=anna), r"Anna · 11/17")
    assert "Hat Trick" in out[0].text() and "**Natural Talent**" in out[0].text()

    # ---------------------------------------------------------------- scheduling
    clk.t = START + 3600   # back to Sunday night (the database doesn't care)
    await step("Players can't schedule", invoke(sched.set_cmd, sched, as_(anna), when="fri 19:30"), "Only the GM")
    await step("Unreadable date", invoke(sched.set_cmd, sched, as_(gm), when="next friday-ish"), "can't read")
    friday = berlin(2026, 10, 9, 19, 30)
    await step("GM sets Friday 19:30 Berlin time, pinging everyone",
               invoke(sched.set_cmd, sched, as_(gm), when="fri 19:30", title="Into the Mines"),
               rf"Into the Mines\*\*: <t:{friday}:F> \(<t:{friday}:R>\)\n\s*I'll remind everyone the day before and an hour "
               rf"before\. <@100> <@200> <@300>")
    await step("Show", invoke(sched.show, sched, as_(ben)), rf"<t:{friday}:F>", "ephemeral")

    assert await sched.check_reminders(friday - 25 * 3600) == 0
    await step("Day-before reminder", sched.check_reminders(friday - 23 * 3600),
               rf"Tomorrow is session day!\*\* \*\*Into the Mines\*\* starts <t:{friday}:F>.*<@100> <@200> <@300>",
               "channel")
    assert await sched.check_reminders(friday - 22 * 3600) == 0, "24h reminder sent twice"
    await step("1h reminder", sched.check_reminders(friday - 30 * 60), rf"Into the Mines\*\* starts <t:{friday}:R>!")
    assert await sched.check_reminders(friday - 10 * 60) == 0
    await step("Game time", sched.check_reminders(friday + 60), r"Game time!\*\* \*\*Into the Mines\*\* starts now!")
    assert await db.get_schedule(1) is None
    await step("Nothing scheduled anymore", invoke(sched.show, sched, as_(ben)), "No session is scheduled")

    await invoke(sched.set_cmd, sched, as_(gm), when="2026-10-20 19:00")
    assert await sched.check_reminders(berlin(2026, 10, 20, 23, 0)) == 0, "stale reminder sent after downtime"
    assert await db.get_schedule(1) is None

    await invoke(sched.set_cmd, sched, as_(gm), when="tomorrow 19:00")
    clk.t = berlin(2026, 10, 5, 18, 30)
    await step("Starting the session clears its schedule", invoke(sess.start, sess, as_(gm)), "Session 6")
    assert await db.get_schedule(1) is None
    await invoke(sess.end, sess, as_(gm))

    # ---------------------------------------------------------------- less than a day away & cancelling
    clk.t = berlin(2026, 10, 6, 12, 0)
    tonight = berlin(2026, 10, 6, 20, 0)
    await step("A session later today: no separate day-before reminder",
               invoke(sched.set_cmd, sched, as_(gm), when="today 20:00"), "I'll remind everyone an hour before\\.")
    assert await sched.check_reminders(tonight - 6 * 3600) == 0, "day-before reminder for a session set today"
    await step("…but the hour-before one comes", sched.check_reminders(tonight - 30 * 60), rf"starts <t:{tonight}:R>!")
    await step("Cancel", invoke(sched.cancel, sched, as_(gm)), r"cancelled.*<@200>")
    await step("Nothing to cancel", invoke(sched.cancel, sched, as_(gm)), "No session is scheduled")

    # ---------------------------------------------------------------- help still fits Discord's limits
    out = await step("/help sessions chapter",
                     invoke(rolling.help, rolling, as_(anna), chapter=Choice(name="Sessions", value="sessions")),
                     "Dice statistics.*Planning the next session")
    e = out[0].embeds[0]
    assert len(e.description) <= 4096 and len(e.title) <= 256
    if VERBOSE:
        print(f"\n{n} steps passed")


def test_phase4_session(tmp_path):
    asyncio.run(run(str(tmp_path / "p4.db")))


if __name__ == "__main__":
    import tempfile
    VERBOSE = True
    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(f"{d}/p4.db"))
