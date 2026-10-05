"""
End-to-end Phase 3: resources, rests, XP & levels, companions, export/import, random tables, notes.
Plus: every autocomplete in the bot (all phases) is exercised the way discord.py calls it.
Run `python -m tests.test_phase3_session` to print the transcript.
"""
import asyncio
import json
import re

from discord.app_commands import Choice

from cogs.campaigns import Campaigns
from cogs.characters import Characters
from cogs.combat import Combat
from cogs.companions import Companions
from cogs.groupcheck import GroupCheck
from cogs.health import Health
from cogs.lore import Lore
from cogs.progress import Progress
from cogs.rolling import Rolling
from core.db import Database
from tests.fake_discord import (
    FakeAttachment, FakeBot, FakeChannel, FakeGuild, FakeInteraction, FakeUser, Recorder, autocomplete, invoke,
    press, submit_modal,
)

VERBOSE = False
ALL_COGS = (Campaigns, Characters, Rolling, Combat, Health, GroupCheck, Progress, Companions, Lore)


async def make_world(db):
    rec = Recorder()
    table = FakeChannel(rec, 50)
    bot = FakeBot(db, [table])
    for cls in ALL_COGS:
        await bot.add_cog(cls(bot))
    gm, anna, ben = FakeUser(rec, 100, "GameMaster"), FakeUser(rec, 200, "Anna"), FakeUser(rec, 300, "Ben")
    guild = FakeGuild(1, [gm, anna, ben])

    def as_(user, message=None):
        return FakeInteraction(rec, user, guild, table, message)

    return rec, bot, (gm, anna, ben), as_


class Stepper:
    def __init__(self, rec):
        self.rec, self.n = rec, 0

    async def __call__(self, title, coro, expect=None, where=None, absent=None):
        self.n += 1
        before = len(self.rec.log)
        await coro
        new = self.rec.log[before:]
        assert new, f"{title}: bot sent nothing"
        out = "\n".join(f"  ({s.where}) " + s.text().replace("\n", "\n  ") for s in new
                        if not s.where.startswith("edit#"))
        if VERBOSE:
            print(f"\n── {self.n}. {title}\n{out}")
        if expect:
            assert re.search(expect, out, re.S), f"{title}: expected /{expect}/ in:\n{out}"
        if where:
            assert any(s.where.startswith(where) for s in new), f"{title}: no '{where}' in {[s.where for s in new]}"
        if absent:
            assert not re.search(absent, out, re.S), f"{title}: /{absent}/ must not appear in:\n{out}"
        return new


async def run(db_path: str):
    db = Database(db_path)
    await db.connect()
    try:
        await _session(db)
    finally:
        await db.close()


async def _session(db):
    rec, bot, (gm, anna, ben), as_ = await make_world(db)
    c = {name: bot.get_cog(name) for name in
         ("Campaigns", "Characters", "Combat", "Health", "Progress", "Companions", "Lore")}
    camp, chars, combat, health, prog, comp, lore = c.values()
    step = Stepper(rec)
    LONG = Choice(name="Long rest", value="long")
    SHORT = Choice(name="Short rest", value="short")

    # ---------------------------------------------------------------- setup
    await invoke(camp.create, camp, as_(gm), name="Strahd")
    await invoke(chars.char_create, chars, as_(anna), name="Lyra")
    await invoke(chars.stat_bulk, chars, as_(anna), entries="dex=4, level=1, max_hp=10+@level*5")
    await invoke(chars.char_create, chars, as_(ben), name="Grom")
    await invoke(chars.stat_bulk, chars, as_(ben), entries="max_hp=30, level=1")
    dash = (await step("Dashboard", invoke(health.dashboard, health, as_(gm)), r"Lyra.*15/15"))[0].id

    # ---------------------------------------------------------------- resources
    await step("Resource with a formula max", invoke(prog.res_add, prog, as_(anna), name="slots_1", max="@level+1"),
               r"slots_1` 2/2 \(refills on long rest\)")
    await step("Short-rest resource starting half empty",
               invoke(prog.res_add, prog, as_(anna), name="ki", max="3", reset=SHORT, current=1), r"ki` 1/3")
    await step("Max referencing a missing stat", invoke(prog.res_add, prog, as_(anna), name="x", max="@nope"),
               "no stat `nope`")
    await step("Use a slot", invoke(prog.res_use, prog, as_(anna), name="slots_1"), r"1/2")
    await step("Use the last slot", invoke(prog.res_use, prog, as_(anna), name="slots_1"), r"0/2 \*\*Empty!")
    await step("Can't overspend", invoke(prog.res_use, prog, as_(anna), name="slots_1"), "only has 0/2")
    await step("Gaining is capped at max", invoke(prog.res_gain, prog, as_(anna), name="ki", amount=5), r"3/3")
    await invoke(prog.res_use, prog, as_(anna), name="ki", amount=2)
    await step("Resource list", invoke(prog.res_list, prog, as_(anna)), r"ki` \*\*1/3.*slots_1` \*\*0/2.*@level\+1")
    assert "slots_1 0/2" in rec.messages[dash].text(), rec.messages[dash].text()

    # ---------------------------------------------------------------- XP & levels
    await step("Players can't award XP", invoke(prog.xp_award, prog, as_(anna), amount=100), "Only the GM")
    await step("GM picks the D&D 5e level table", invoke(prog.xp_table, prog, as_(gm), thresholds="dnd5e"),
               "20 levels")
    await step("300 XP each: both reach level 2",
               invoke(prog.xp_award, prog, as_(gm), amount=300, reason="the goblin cave"),
               r"300 XP\*\* each for \*the goblin cave\*.*Grom\*\* reached \*\*level 2.*Lyra\*\* reached \*\*level 2")
    await step("Leveling recalculates derived stats", invoke(chars.char_show, chars, as_(anna)),
               r"\*\*20\*\*/20.*`Level\s*` \*\*2\*\*.*`Max HP\s*` \*\*20\*\*")
    await step("Resource max follows the level", invoke(prog.res_list, prog, as_(anna)), r"slots_1` \*\*0/3")
    await step("Split 1000 XP: 500 each, no level-up",
               invoke(prog.xp_award, prog, as_(gm), amount=1000, split=True), r"500 XP", absent="reached")
    await step("GM sets XP directly", invoke(prog.xp_set, prog, as_(gm), target="lyra", amount=2700),
               r"level 4.*Level is now \*\*4")
    await step("XP progress", invoke(prog.xp_show, prog, as_(anna)), r"2,700 XP · level 4 · .*3,800 to level 5")
    await invoke(chars.stat_set, chars, as_(ben), name="level", value="2+0")
    await step("A formula `level` stat is never overwritten",
               invoke(prog.xp_award, prog, as_(gm), amount=6000, target="Grom"), r"Grom\*\* reached \*\*level 5")
    assert (await db.get_stats((await db.find_characters(1, "Grom"))[0].id))["level"] == "2+0"

    # ---------------------------------------------------------------- rests
    await invoke(health.damage, health, as_(gm), amount="15", target="Lyra")
    await step("Short rest refills only short-rest resources",
               invoke(prog.rest_cmd, prog, as_(anna), kind=SHORT), r"Short rest.*Lyra\*\*: ki 1→3", absent="slots|HP")
    await step("Party rest is GM only", invoke(prog.rest_cmd, prog, as_(anna), kind=LONG, party=True), "Only the GM")
    await step("Long party rest refills slots and HP",
               invoke(prog.rest_cmd, prog, as_(gm), kind=LONG, party=True),
               r"Long rest.*Grom\*\*: nothing to restore.*Lyra\*\*: slots_1 0→5, HP 15→30")

    # ---------------------------------------------------------------- companions
    await step("Lyra gets a companion", invoke(comp.add, comp, as_(anna), name="Whiskers"),
               r"Whiskers\*\* is now \*\*Lyra\*\*'s companion")
    await step("Duplicate companion name", invoke(comp.add, comp, as_(anna), name="whiskers"), "already have")
    await step("Roll for the companion, posted as it",
               invoke(comp.roll, comp, as_(anna), name="Whiskers", expression="1d20+2"), r"Results for Whiskers.*# \d+")
    await step("The companion has its own stats", invoke(comp.roll, comp, as_(anna), name="Whiskers",
                                                          expression="1d20+@dex"), r"Whiskers\*\* has no stat `dex`")
    await invoke(chars.char_use, chars, as_(anna), name="Whiskers")
    await invoke(chars.stat_bulk, chars, as_(anna), entries="max_hp=4, dex=3")
    await invoke(chars.skill_add, chars, as_(anna), name="bite", formula="1d20+@dex")
    await step("Companion stats and skills editable after switching", invoke(chars.char_list, chars, as_(anna)),
               r"Lyra.*Whiskers · \*active\* · companion of Lyra")
    await invoke(chars.char_use, chars, as_(anna), name="Lyra")
    await step("Companion skill roll without switching",
               invoke(comp.roll, comp, as_(anna), name="whiskers", expression="bite"), r"Results for Whiskers.*Bite.*dex\(3\)")
    assert re.search(r"Whiskers.*4/4.*Lyra", rec.messages[dash].text(), re.S), rec.messages[dash].text()

    await invoke(combat.start, combat, as_(gm))
    await step("Companion joins the fight", invoke(comp.join, comp, as_(anna), name="Whiskers", initiative="12"),
               r"Whiskers\*\* rolls initiative: \*\*12")
    await step("…and can be hurt", invoke(health.damage, health, as_(gm), amount="3", target="Whiskers"), r"1/4")
    await invoke(combat.end, combat, as_(gm))
    await step("Party long rest includes companions",
               invoke(prog.rest_cmd, prog, as_(gm), kind=LONG, party=True), r"Whiskers\*\*: HP 1→4")

    await invoke(chars.char_use, chars, as_(anna), name="Whiskers")
    await step("XP goes to the owner even while playing the companion",
               invoke(prog.xp_award, prog, as_(gm), amount=10), r"Lyra\*\* \+10", absent=r"Whiskers\*\* \+")
    await invoke(chars.char_use, chars, as_(anna), name="Lyra")

    # ---------------------------------------------------------------- export / import
    out = await step("Export Lyra", invoke(chars.char_export, chars, as_(anna)), "with 1 companion", "ephemeral")
    exported = out[0].file
    raw = exported.fp.read()
    data = json.loads(raw)
    assert exported.filename == "Lyra.json"
    assert data["name"] == "Lyra" and data["xp"] == 2710 and data["stats"]["level"] == "4"
    assert data["companions"][0]["name"] == "Whiskers" and data["companions"][0]["skills"][0]["name"] == "bite"
    assert {r["name"] for r in data["resources"]} == {"slots_1", "ki"}

    await step("Re-import clashes with the existing name",
               invoke(chars.char_import, chars, as_(anna), file=FakeAttachment("Lyra.json", raw)), "already have")
    await step("Renaming the main character isn't enough: the companion clashes too",
               invoke(chars.char_import, chars, as_(anna), file=FakeAttachment("Lyra.json", raw), name="Lyra II"),
               r"Whiskers")
    await step("Ben imports it into his own roster",
               invoke(chars.char_import, chars, as_(ben), file=FakeAttachment("Lyra.json", raw)),
               r"Imported \*\*Lyra\*\* with companions Whiskers")
    await step("Everything came along", invoke(chars.char_show, chars, as_(ben)),
               r"\*\*30\*\*/30.*2,710 XP · level 4.*`ki` ▰+ \*\*3\*\*/3.*`slots_1` ▰+ \*\*5\*\*/5"
               r".*Companions: Whiskers")
    await step("Garbage file", invoke(chars.char_import, chars, as_(ben), file=FakeAttachment("x.json", b"{nope")),
               "isn't valid JSON")
    evil = dict(data, stats={"dex": "1" * 500})
    await step("Tampered file is rejected before anything is written",
               invoke(chars.char_import, chars, as_(ben), file=FakeAttachment("x.json", json.dumps(evil).encode()),
                      name="Evil"), "Import failed")
    assert not await db.get_character_by_name(1, 300, "Evil")
    await step("Dismiss the companion", invoke(comp.remove, comp, as_(anna), name="Whiskers"), "leaves")

    # ---------------------------------------------------------------- random tables
    await step("Players can't create tables", invoke(lore.table_create, lore, as_(anna), name="Forest",
                                                     entries="x"), "Only the GM")
    await step("GM creates a table inline",
               invoke(lore.table_create, lore, as_(gm), name="Forest",
                      entries="3* [[1d4+1]] wolves; a lost {occupation}; 2* nothing happens"), "3 entries")
    inter = as_(gm)
    await step("No entries opens the editor", invoke(lore.table_create, lore, inter, name="Ruins"), "modal")
    await step("Submitting the editor saves it",
               submit_modal(inter.modal, as_(gm), entries="A crumbling tower\n2* {loot}"),
               "Ruins\\*\\* saved with 2 entries")
    inter = as_(gm)
    await invoke(lore.table_create, lore, inter, name="Broken")
    await step("Editor with a broken roll shows an error", submit_modal(inter.modal, as_(gm),
                                                                       entries="[[2d]] rats"), "")
    out = await step("Anyone can roll", invoke(lore.table_roll, lore, as_(anna), name="forest", count=3),
                     r"Forest.*•.*•.*•", "reply")
    assert "{" not in out[0].text() and "[[" not in out[0].text()
    await step("Private roll", invoke(lore.table_roll, lore, as_(anna), name="Ruins", private=True),
               "Ruins", "ephemeral")
    await step("Add one entry", invoke(lore.table_add, lore, as_(gm), name="forest", entry="a bear", weight=1),
               r"Forest\*\* \(4 entries")
    await step("GM sees probabilities", invoke(lore.table_show, lore, as_(gm), name="Forest"),
               r"42\.9%.*wolves.*14\.3%.*a bear")
    inter = as_(gm)
    await step("Built-in tables can be customised", invoke(lore.table_edit, lore, inter, name="npc"), "modal")
    assert "{name}" in inter.modal.entries.default
    await submit_modal(inter.modal, as_(gm), entries="**{name}**, a mysterious stranger")
    await step("…and the campaign's version wins", invoke(lore.table_roll, lore, as_(ben), name="npc"),
               r"mysterious stranger")
    await step("/generate uses built-ins", invoke(lore.generate, lore, as_(ben),
                                                  kind=Choice(name="Tavern", value="tavern")), r"\*\*The \w")
    await step("Unknown table", invoke(lore.table_roll, lore, as_(ben), name="dragons"), "No table")
    await step("Table list", invoke(lore.table_list, lore, as_(ben)), r"Forest.*npc.*Ruins.*Built-in.*loot")
    await step("Delete a table", invoke(lore.table_delete, lore, as_(gm), name="Forest"), "deleted")

    # ---------------------------------------------------------------- notes
    await step("Player writes a note", invoke(lore.note_add, lore, as_(anna), title="Mayor Ulric",
                                              category=Choice(name="NPC", value="NPC"),
                                              text="Bald, nervous, owes the guild money."), "Saved")
    await step("Players can't write GM-only notes",
               invoke(lore.note_add, lore, as_(anna), title="X", gm_only=True, text="x"), "Only the GM")
    inter = as_(gm)
    await step("GM writes a secret note in the editor",
               invoke(lore.note_add, lore, inter, title="Ulric's secret", gm_only=True), "modal")
    await step("…and saves it", submit_modal(inter.modal, as_(gm), content="He is secretly a vampire."), "GM only")
    await step("Players' search hides GM notes", invoke(lore.note_search, lore, as_(anna), query="ulric"),
               "Mayor Ulric", absent="secret")
    await step("GM search finds both", invoke(lore.note_search, lore, as_(gm), query="ulric"),
               r"Ulric's secret\*\*.*Mayor Ulric")
    await step("Search in the text", invoke(lore.note_search, lore, as_(gm), query="vampire"), "Ulric's secret")
    await step("Players can't open GM notes", invoke(lore.note_show, lore, as_(anna), title="Ulric's secret"),
               "No note")
    await step("GM notes can't be posted publicly",
               invoke(lore.note_show, lore, as_(gm), title="Ulric's secret", public=True), "can't be posted")
    await step("Ben can't edit Anna's note", invoke(lore.note_edit, lore, as_(ben), title="Mayor Ulric"),
               "author or the GM")
    inter = as_(anna)
    await invoke(lore.note_edit, lore, inter, title="mayor ulric")
    assert inter.modal.content.default.startswith("Bald")
    await step("Anna edits her note", submit_modal(inter.modal, as_(anna), content="Bald. Actually a nice guy."),
               "nice guy")
    await step("Share a note with the table", invoke(lore.note_show, lore, as_(ben), title="Mayor Ulric", public=True),
               r"Mayor Ulric.*nice guy", "reply")
    await step("Note list by category", invoke(lore.note_list, lore, as_(gm)), r"Lore.*Ulric's secret.*NPC.*Mayor")
    await step("Ben can't delete it", invoke(lore.note_delete, lore, as_(ben), title="Mayor Ulric"), "author or the GM")
    out = await step("Anna deletes it (with confirmation)",
                     invoke(lore.note_delete, lore, as_(anna), title="Mayor Ulric"), "Delete the note")
    await press(out[0].view.confirm, as_(anna, out[0]))
    assert "deleted" in rec.messages[out[0].id].text()
    assert await db.get_note(1, "Mayor Ulric") is None

    # ---------------------------------------------------------------- help still fits Discord's limits
    rolling = bot.get_cog("Rolling")
    out = await step("/help world building chapter",
                     invoke(rolling.help, rolling, as_(anna), chapter=Choice(name="World building", value="world")),
                     "Random tables.*Notes")
    e = out[0].embeds[0]
    assert len(e.description) <= 4096 and len(e.title) <= 256
    if VERBOSE:
        print(f"\n{step.n} steps passed")


async def autocomplete_check(db_path: str):
    """Every autocomplete in every phase, called the way discord.py calls it."""
    db = Database(db_path)
    await db.connect()
    try:
        rec, bot, (gm, anna, ben), as_ = await make_world(db)
        g = bot.get_cog
        camp, chars, combat, health, prog, comp, lore, rolling = (
            g(n) for n in ("Campaigns", "Characters", "Combat", "Health", "Progress", "Companions", "Lore",
                           "Rolling"))
        await invoke(camp.create, camp, as_(gm), name="Strahd")
        await invoke(chars.char_create, chars, as_(anna), name="Lyra")
        await invoke(chars.stat_bulk, chars, as_(anna), entries="dex=4, max_hp=10")
        await invoke(chars.skill_add, chars, as_(anna), name="stealth", formula="1d20+@dex")
        await invoke(chars.macro_save, chars, as_(anna), name="fireball", expression="8d6")
        await invoke(prog.res_add, prog, as_(anna), name="slots_1", max="3")
        await invoke(comp.add, comp, as_(anna), name="Whiskers")
        await invoke(chars.char_create, chars, as_(ben), name="Grom")
        await invoke(combat.monster_save, combat, as_(gm), name="Goblin", hp="7")
        await invoke(combat.start, combat, as_(gm))
        await invoke(combat.join, combat, as_(anna), initiative="10")
        await invoke(combat.spawn, combat, as_(gm), template="Goblin", count=2)
        await invoke(health.condition_add, health, as_(gm), name="Prone", target="Goblin 1")
        await invoke(lore.table_create, lore, as_(gm), name="Forest", entries="wolves")
        await invoke(lore.note_add, lore, as_(anna), title="Mayor", text="nice")
        await invoke(lore.note_add, lore, as_(gm), title="Secret", gm_only=True, text="vampire")

        # 1) every autocomplete in the bot runs without errors, for a player and for the GM
        count = 0
        for cog in bot._cogs.values():
            stack = list(cog.__cog_app_commands__)
            while stack:
                cmd = stack.pop()
                if hasattr(cmd, "commands"):
                    stack += cmd.commands
                    continue
                for pname, p in cmd._params.items():
                    if p.autocomplete:
                        for user in (anna, gm):
                            await autocomplete(cmd, as_(user), pname, "")
                        count += 1
        assert count >= 30, count

        # 2) the suggestions are the right ones
        async def ac(cmd, user, param, current="", **ns):
            return await autocomplete(cmd, as_(user), param, current, **ns)

        assert await ac(rolling.check, anna, "skill") == ["stealth"]
        assert await ac(chars.char_use, anna, "name") == ["Lyra", "Whiskers"]
        assert await ac(chars.char_use, anna, "name", "whi") == ["Whiskers"]
        assert await ac(chars.stat_remove, anna, "name", "de") == ["dex"]
        assert await ac(chars.macro_remove, anna, "name") == ["fireball"]
        assert await ac(chars.char_use, ben, "name") == ["Grom"]
        assert await ac(camp.link, gm, "name") == ["Strahd"]
        assert set(await ac(combat.remove, gm, "name")) == {"Lyra", "Goblin 1", "Goblin 2"}
        assert await ac(combat.spawn, gm, "template") == ["Goblin"]
        assert await ac(combat.spawn, anna, "template") == []            # no spoilers for players
        targets = await ac(health.damage, gm, "target")
        assert {"Lyra", "Goblin 1", "Goblin 2", "Grom", "Whiskers"} <= set(targets)
        assert await ac(health.condition_remove, gm, "name", target="Goblin 1") == ["Prone"]
        assert await ac(health.condition_remove, gm, "name", target="Lyra") == []
        assert "Stunned" in await ac(health.condition_add, gm, "name", "stu")
        assert await ac(prog.res_use, anna, "name") == ["slots_1"]
        assert await ac(prog.xp_award, gm, "target") == ["Grom", "Lyra"]  # companions don't get XP
        assert await ac(comp.roll, anna, "name") == ["Whiskers"]
        assert await ac(comp.roll, ben, "name") == []
        rolls = await ac(lore.table_roll, anna, "name")
        assert rolls[0] == "Forest" and "npc" in rolls and "loot" in rolls
        assert await ac(lore.table_delete, gm, "name") == ["Forest"]       # built-ins can't be deleted
        assert await ac(lore.note_show, anna, "title") == ["Mayor"]         # GM notes hidden
        assert set(await ac(lore.note_show, gm, "title")) == {"Mayor", "Secret"}
        if VERBOSE:
            print(f"{count} autocomplete parameters run, suggestions verified")
    finally:
        await db.close()


def test_phase3_session(tmp_path):
    asyncio.run(run(str(tmp_path / "p3.db")))


def test_all_autocompletes(tmp_path):
    asyncio.run(autocomplete_check(str(tmp_path / "ac.db")))


if __name__ == "__main__":
    import tempfile
    VERBOSE = True
    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(f"{d}/p3.db"))
        asyncio.run(autocomplete_check(f"{d}/ac.db"))
