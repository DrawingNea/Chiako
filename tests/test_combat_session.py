"""
End-to-end Phase 2: a full fight with initiative, monsters, HP, timed conditions, group checks and the
live dashboard, through the real cogs and a real SQLite database.
Run `python -m tests.test_combat_session` to print the whole transcript.
"""
import asyncio
import re

import aiosqlite

from cogs.campaigns import Campaigns
from cogs.characters import Characters
from cogs.combat import Combat, TrackerView
from cogs.groupcheck import GroupCheck
from cogs.health import Health
from cogs.rolling import Rolling
from core.db import Database
from tests.fake_discord import (
    FakeBot, FakeChannel, FakeGuild, FakeInteraction, FakeUser, Recorder, invoke, press,
)

VERBOSE = False


async def run(db_path: str):
    db = Database(db_path)
    await db.connect()
    try:
        await _fight(db)
    finally:
        await db.close()


async def _fight(db):
    rec = Recorder()
    table = FakeChannel(rec, 50)
    bot = FakeBot(db, [table])
    for cls in (Campaigns, Characters, Rolling, Combat, Health, GroupCheck):
        await bot.add_cog(cls(bot))
    camp, chars, combat, health, group = (bot.get_cog(n) for n in
                                          ("Campaigns", "Characters", "Combat", "Health", "GroupCheck"))

    gm, anna, ben = FakeUser(rec, 100, "GameMaster"), FakeUser(rec, 200, "Anna"), FakeUser(rec, 300, "Ben")
    guild = FakeGuild(1, [gm, anna, ben])

    def as_(user, message=None):
        return FakeInteraction(rec, user, guild, table, message)

    n = 0

    async def step(title, coro, expect=None, where=None, absent=None):
        nonlocal n
        n += 1
        before = len(rec.log)
        await coro
        new = rec.log[before:]
        assert new, f"{title}: bot sent nothing"
        out = "\n".join(f"  ({s.where}) " + s.text().replace("\n", "\n  ") for s in new)
        if VERBOSE:
            print(f"\n── {n}. {title}\n{out}")
        if expect:
            assert re.search(expect, out, re.S), f"{title}: expected /{expect}/ in:\n{out}"
        if where:
            assert any(s.where.startswith(where) for s in new), f"{title}: no '{where}' message in {[s.where for s in new]}"
        if absent:
            assert not re.search(absent, out, re.S), f"{title}: /{absent}/ must not appear in:\n{out}"
        return new

    async def tracker():
        enc = await db.get_active_encounter(1)
        return rec.messages[enc.tracker_message_id]

    async def tracker_text():
        return (await tracker()).text()

    # ---------------------------------------------------------------- setup
    await invoke(camp.create, camp, as_(gm), name="Strahd")
    await invoke(chars.char_create, chars, as_(anna), name="Lyra")
    await invoke(chars.stat_bulk, chars, as_(anna), entries="dex=4, max_hp=16")
    await invoke(chars.skill_add, chars, as_(anna), name="initiative", formula="20")
    await invoke(chars.char_create, chars, as_(ben), name="Grom")
    await invoke(chars.stat_set, chars, as_(ben), name="max_hp", value="30")

    await step("Player can't make monster templates",
               invoke(combat.monster_save, combat, as_(anna), name="Goblin"), "Only the GM")
    await step("Bad template formula is rejected",
               invoke(combat.monster_save, combat, as_(gm), name="Goblin", hp="2d"), "")
    await step("GM saves a Goblin template",
               invoke(combat.monster_save, combat, as_(gm), name="Goblin", hp="7", initiative="10", ac=15,
                      notes="Nimble escape"), "Template \\*\\*Goblin\\*\\* saved")
    await step("GM sets the campaign initiative formula",
               invoke(camp.init_formula, camp, as_(gm), formula="1d20+@dex"), "1d20\\+@dex")
    dash = await step("Anna posts the party dashboard",
                      invoke(health.dashboard, health, as_(anna)), r"Grom.*30/30.*Lyra.*16/16.*Out of combat")
    dash_id = dash[0].id

    # ---------------------------------------------------------------- start & join
    await step("Only the GM can start a fight", invoke(combat.start, combat, as_(anna)), "Only the GM")
    await step("GM starts the fight", invoke(combat.start, combat, as_(gm)), "Roll for initiative", "reply")
    await step("Second fight is refused", invoke(combat.start, combat, as_(gm)), "already running")
    t = await tracker()
    await step("Lyra joins with the button (uses her 'initiative' skill)",
               press(t.view.join, as_(anna, t)), r"Lyra\*\* rolls initiative: \*\*20")
    await step("Grom joins: campaign formula needs @dex he doesn't have",
               invoke(combat.join, combat, as_(ben)), "no stat `dex`")
    await step("Grom joins with an explicit number", invoke(combat.join, combat, as_(ben), initiative="15"),
               r"\*\*15\*\*")
    await step("…but only once", invoke(combat.join, combat, as_(ben), initiative="3"), "already in the fight")
    await step("GM adds a boss", invoke(combat.add, combat, as_(gm), name="Goblin Boss", initiative="18",
                                         hp="20", ac=17), "initiative 18, HP 20", "ephemeral")
    await step("GM spawns 2 goblins from the template",
               invoke(combat.spawn, combat, as_(gm), template="goblin", count=2), "Goblin 1.*Goblin 2")
    text = await tracker_text()
    order = re.findall(r"\*\*(Lyra|Goblin Boss|Grom|Goblin 1|Goblin 2)\*\*", text)
    assert order[:3] == ["Lyra", "Goblin Boss", "Grom"] and set(order[3:]) == {"Goblin 1", "Goblin 2"}, order
    assert "16/16" in text and "Unhurt" in text and "20/20" not in text, "tracker leaks monster HP:\n" + text
    if VERBOSE:
        print("\n── tracker after joining:\n  " + text.replace("\n", "\n  "))

    # ---------------------------------------------------------------- round 1
    await step("Players can't start combat", press(t.view.next_turn, as_(anna, t)), "Only the GM")
    await step("GM presses Start: round 1, Lyra pinged",
               press(t.view.next_turn, as_(gm, t)), r"Round 1.*Lyra\*\*'s turn! <@200>")
    assert "` 20` **Lyra**" in await tracker_text()
    await step("Anna stuns the boss for 1 round (prefix match on the name)",
               invoke(health.condition_add, health, as_(anna), name="stunned", target="goblin b", rounds=1),
               r"Goblin Boss\*\* is now \*\*Stunned\*\* for \*\*1\*\* round")
    await step("Lyra hits the boss for 12: players only see 'Bloodied'",
               invoke(health.damage, health, as_(anna), amount="12", target="Goblin Boss"),
               r"takes \*\*12\*\* damage → Bloodied", absent=r"8/20")
    await step("Ben can't end Lyra's turn", invoke(combat.next_cmd, combat, as_(ben)), "whose turn")
    await step("Anna ends her own turn", invoke(combat.next_cmd, combat, as_(anna)),
               r"Goblin Boss\*\*'s turn!.*Stunned \(1\)")
    await step("Boss's turn ends: Stunned wears off, Grom is up",
               invoke(combat.next_cmd, combat, as_(gm)),
               r"Goblin Boss\*\* is no longer \*\*Stunned.*Grom\*\*'s turn! <@300>")
    await step("Boss hits Grom for 10", invoke(health.damage, health, as_(gm), amount="10", target="Grom"),
               r"20/30")
    await step("Grom gets 5 temp HP", invoke(health.temp, health, as_(ben), amount="5"), r"20/30 \+5 temp")
    await step("Temp HP absorbs damage first",
               invoke(health.damage, health, as_(gm), amount="7", target="Grom"),
               r"5 absorbed by temp HP → .*18/30")
    await step("Grom is poisoned for 2 rounds, with a note",
               invoke(health.condition_add, health, as_(gm), name="Poisoned", target="Grom", rounds=2,
                      note="DC 12 Con save ends"), "Poisoned.*2.*rounds.*DC 12")
    await step("Ben ends his turn: poison was applied this turn, so it does not tick yet",
               invoke(combat.next_cmd, combat, as_(ben)), r"Goblin [12]\*\*'s turn", absent="no longer")
    enc = await db.get_active_encounter(1)
    first_goblin = (await db.get_combatant(enc.current_id)).name
    other_goblin = "Goblin 2" if first_goblin == "Goblin 1" else "Goblin 1"
    await step(f"Lyra kills {first_goblin} with a rolled amount",
               invoke(health.damage, health, as_(anna), amount="2d6+10", target=first_goblin),
               rf"{first_goblin}\*\* is defeated!")
    await step("GM ends goblin turn", invoke(combat.next_cmd, combat, as_(gm)), rf"{other_goblin}\*\*'s turn")
    await step("Round 2 begins with Lyra", invoke(combat.next_cmd, combat, as_(gm)), r"Round 2.*Lyra")

    # ---------------------------------------------------------------- round 2
    await invoke(combat.next_cmd, combat, as_(anna))                     # -> boss
    await invoke(combat.next_cmd, combat, as_(gm))                       # -> Grom
    await step("Ben ends his turn: poison ticks to 1 (it was applied on his own turn), dead goblin skipped",
               invoke(combat.next_cmd, combat, as_(ben)),
               rf"{other_goblin}\*\*'s turn", absent=rf"{first_goblin}\*\*'s turn|no longer")
    assert "Poisoned (1)" in await tracker_text()
    await step("Healing is capped at max HP", invoke(health.heal, health, as_(anna), amount="100", target="Grom"),
               r"30/30")
    await step("Anna can't set Grom's HP", invoke(health.set_hp, health, as_(anna), hp=1, target="Grom"),
               "only set your own")
    await step("Ben sets his own HP", invoke(health.set_hp, health, as_(ben), hp=25), "25/30")
    await step("Characters' max HP comes from the stat",
               invoke(health.set_hp, health, as_(ben), hp=25, max_hp=40), "max_hp")
    await step("Players see vague monster HP", invoke(health.show, health, as_(anna), target="Goblin Boss"),
               "Bloodied", absent="8/20")
    await step("GM sees exact monster HP", invoke(health.show, health, as_(gm), target="Goblin Boss"), "8/20")
    await step("Unknown target", invoke(health.damage, health, as_(gm), amount="3", target="Dracula"),
               "can't find")
    await step("Players can't open the GM view", invoke(combat.show, combat, as_(anna), details=True), "Only the GM")
    await step("GM view shows exact HP and AC", invoke(combat.show, combat, as_(gm), details=True),
               r"GM view.*8/20 · AC 17", "ephemeral")
    old_tracker = (await tracker()).id
    await step("Re-posting the tracker moves it down", invoke(combat.show, combat, as_(anna)), r"Round 2", "reply")
    assert (await tracker()).id != old_tracker and rec.messages[old_tracker].view is None

    # ---------------------------------------------------------------- persistence & removal
    persistent = bot.persistent_views[0]
    assert isinstance(persistent, TrackerView) and persistent.timeout is None
    await step("Persistent 'Next' button works for a message from before a restart",
               press(persistent.next_turn, as_(gm, rec.messages[old_tracker])), r"Round 3.*Lyra")
    await step("Ben can't remove a monster", invoke(combat.remove, combat, as_(ben), name="Goblin Boss"),
               "only remove your own")
    await invoke(combat.next_cmd, combat, as_(anna))                      # -> boss
    await step("GM removes the boss on its own turn: turn passes on",
               invoke(combat.remove, combat, as_(gm), name="Goblin Boss"), "left the fight")
    enc = await db.get_active_encounter(1)
    assert (await db.get_combatant(enc.current_id)).name == "Grom", "turn didn't pass to Grom"
    await step("GM moves Grom up in the order", invoke(combat.move, combat, as_(gm), name="Grom", initiative=25),
               "initiative 25")
    assert re.search(r"Grom.*Lyra", await tracker_text(), re.S)

    # ---------------------------------------------------------------- dashboard & sheet
    d = rec.messages[dash_id].text()
    assert re.search(r"Grom.*25/30.*Lyra.*16/16.*round 3.*Grom's turn", d, re.S), d
    if VERBOSE:
        print("\n── dashboard (live-updated):\n  " + d.replace("\n", "\n  "))
    await step("Character sheet shows HP and conditions",
               invoke(chars.char_show, chars, as_(ben)), r"▰+▱* \*\*25\*\*/30.*Poisoned \(1\)")

    await step("Ben ends his turn in round 3: now the poison wears off",
               invoke(combat.next_cmd, combat, as_(ben)), r"Grom\*\* is no longer \*\*Poisoned")

    # ---------------------------------------------------------------- group checks
    gc = await step("Only the GM starts group checks",
                    invoke(group.group_check, group, as_(anna), roll="1d20"), "Only the GM")
    gc = await step("GM calls a DC 10 check", invoke(group.group_check, group, as_(gm), roll="1d20+@dex", dc=10,
                                                     label="Dodge the rocks"), "Dodge the rocks.*DC 10")
    msg = gc[0]
    await step("Anna rolls (dex 4)", press(msg.view.roll, as_(anna, msg)), r"Lyra\*\*: \*\*\d+")
    await step("…only once", press(msg.view.roll, as_(anna, msg)), "already rolled")
    await step("Grom has no dex: helpful error", press(msg.view.roll, as_(ben, msg)), "no stat `dex`", "ephemeral")
    await step("Anna can't close it", press(msg.view.close, as_(anna, msg)), "Only the GM")
    await step("GM closes it", press(msg.view.close, as_(gm, msg)), r"Closed.*\d/1 passed")

    gc = await step("GM calls a secret check", invoke(group.group_check, group, as_(gm), roll="1d20",
                                                      label="Insight", secret=True), "Insight")
    msg = gc[0]
    await step("Anna rolls: result hidden", press(msg.view.roll, as_(anna, msg)),
               r"Lyra\*\* rolled.*Only the GM sees", absent=r"Lyra\*\*: ")
    await press(msg.view.roll, as_(ben, msg))
    await step("Players can't peek", press(msg.view.gm_results, as_(anna, msg)), "Only the GM")
    await step("GM sees the results privately", press(msg.view.gm_results, as_(gm, msg)),
               r"Lyra\*\*: \*\*\d+.*Grom\*\*: \*\*\d+|Grom\*\*: \*\*\d+.*Lyra\*\*: \*\*\d+", "ephemeral")

    # ---------------------------------------------------------------- the end
    tracker_id = (await tracker()).id
    await step("GM ends the fight", invoke(combat.end, combat, as_(gm)), "over after \\*\\*3\\*\\* rounds")
    assert "Fight over after 3 rounds" in rec.messages[tracker_id].text()
    assert rec.messages[tracker_id].view is None
    assert "Out of combat" in rec.messages[dash_id].text()
    await step("No fight, no turns", invoke(combat.next_cmd, combat, as_(gm)), "no fight going on")
    await step("New fights work after ending", invoke(combat.start, combat, as_(gm)), "Roll for initiative")

    async with db.conn.execute("SELECT COUNT(*) FROM conditions") as cur:
        assert (await cur.fetchone())[0] == 0, "expired conditions were not cleaned up"
    if VERBOSE:
        print(f"\n{n} steps passed")


async def migration_check(path: str):
    """A Phase 1 database gets the new columns and tables automatically."""
    async with aiosqlite.connect(path) as conn:
        await conn.executescript("""
            CREATE TABLE campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
              name TEXT NOT NULL COLLATE NOCASE, gm_user_id INTEGER NOT NULL, gm_role_id INTEGER,
              use_webhooks INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, UNIQUE (guild_id, name));
            INSERT INTO campaigns (guild_id, name, gm_user_id, created_at) VALUES (1, 'Old', 5, 0);
        """)
        await conn.commit()
    db = Database(path)
    await db.connect()
    try:
        c = await db.get_campaign(1)
        assert c.name == "Old" and c.init_formula == "1d20" and c.dashboard_message_id is None
        await db.create_encounter(1, 99)
        assert await db.get_active_encounter(1)
    finally:
        await db.close()


def test_combat_session(tmp_path):
    asyncio.run(run(str(tmp_path / "combat.db")))


def test_migration_from_phase1(tmp_path):
    asyncio.run(migration_check(str(tmp_path / "old.db")))


if __name__ == "__main__":
    import tempfile
    VERBOSE = True
    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(f"{d}/combat.db"))
        asyncio.run(migration_check(f"{d}/old.db"))
        print("Phase 1 database migrated fine")
