"""
End-to-end Phase 5: campaign language (German), inventory & money with the party stash, and the character sheet card.
Run `python -m tests.test_phase5_session` to print the transcript.
"""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from discord.app_commands import Choice

from cogs.inventory import STASH, Inventory
from cogs.schedule import Scheduling
from core import clock
from tests.fake_discord import FakeAttachment, FakeMessage, autocomplete, invoke, press, submit_modal
from tests.test_phase3_session import Stepper, make_world

VERBOSE = False
BERLIN = ZoneInfo("Europe/Berlin")


async def run(db_path: str):
    from core.db import Database
    db = Database(db_path)
    await db.connect()
    real_now = clock.now
    try:
        await _session(db)
    finally:
        clock.now = real_now
        await db.close()


async def _session(db):
    import tests.test_phase3_session as p3
    p3.VERBOSE = VERBOSE
    rec, bot, (gm, anna, ben), as_ = await make_world(db)
    await bot.add_cog(Inventory(bot))
    await bot.add_cog(Scheduling(bot))
    camp, chars, rolls, inv, sched = (bot.get_cog(n) for n in ("Campaigns", "Characters", "Rolling", "Inventory",
                                                              "Scheduling"))
    step = Stepper(rec)
    table = bot.get_channel(50)

    async def say(user, text):
        await rolls.on_message(FakeMessage(rec, user, as_(user).guild, table, text))

    await invoke(camp.create, camp, as_(gm), name="Das Schwarze Auge")
    await invoke(chars.char_create, chars, as_(anna), name="Lyra")
    await invoke(chars.stat_bulk, chars, as_(anna), entries="mu=12, ge=14, kk=11, level=1, max_hp=20")
    await invoke(chars.char_create, chars, as_(ben), name="Grom")

    # ---------------------------------------------------------------- language
    await step("Players can't change the language",
               invoke(camp.language, camp, as_(anna), language=Choice(name="Deutsch", value="de")), "Only the GM")
    await step("GM switches the campaign to German",
               invoke(camp.language, camp, as_(gm), language=Choice(name="Deutsch", value="de")),
               r"Diese Kampagne spricht jetzt \*\*Deutsch\*\*")
    await step("German dice notation and a German result card", invoke(rolls.r, rolls, as_(anna), expression="2W6+3"),
               r"Ergebnis für Lyra.*2 × W6 \+ 3.*# \d+")
    await step("German dice rules", invoke(camp.dice, camp, as_(gm), sides=10, success=8, explode=10),
               r"Würfelregeln · Das Schwarze Auge.*W10 · Erfolg ab 8 · 10er explodieren")
    await step("A pool in German", invoke(rolls.check, rolls, as_(anna), skill="5"),
               r"5 × W10 · Erfolg bei ≥ 8 · 10er explodieren.*# (\d Erfolge?|Keine Erfolge)")
    await step("Inline roll: the sentence comes back with a German result",
               say(anna, "Ich klettere [[3]] Meter hoch!"), r"### Ich klettere \*\*(\d Erfolge? ✨|Keine Erfolge 💤)\*\*")
    await step("Mention help in German", say(anna, "<@1> hilfe"), "Sprich mich an, um zu würfeln")
    out = await step("/help in German", invoke(rolls.help, rolls, as_(anna)), r"Erste Schritte.*Kapitel 1 von 12")
    await step("…next chapter", press(out[-1].view.next_page, as_(anna)), r"Würfeln.*So schreibst du einen Wurf")

    start = int(datetime(2026, 10, 4, 20, 0, tzinfo=BERLIN).timestamp())   # a Sunday evening
    clock.now = lambda: start
    await invoke(camp.timezone, camp, as_(gm), name="Europe/Berlin")
    friday = int(datetime(2026, 10, 9, 19, 30, tzinfo=BERLIN).timestamp())
    await step("German dates", invoke(sched.set_cmd, sched, as_(gm), when="Freitag 19:30 Uhr"),
               rf"Nächste Spielrunde: <t:{friday}:F>.*am Tag vorher")
    await step("German day-before reminder", sched.check_reminders(friday - 23 * 3600),
               r"Morgen ist Spieltag!\*\* Die Spielrunde beginnt")

    # ---------------------------------------------------------------- inventory & money
    await step("Item into Lyra's inventory",
               invoke(inv.item_add, inv, as_(anna), name="Seil", amount=2, note="15 m"),
               r"Lyra\*\* bekommt \*\*2× Seil\*\* \(jetzt 2\)")
    await step("Item into the party stash", invoke(inv.item_add, inv, as_(anna), name="Heiltrank", amount=3, stash=True),
               r"Das Gruppeninventar bekommt \*\*3× Heiltrank\*\*")
    await step("Players can't hand out items to others",
               invoke(inv.item_add, inv, as_(ben), name="Gold", character="Lyra"), "Only the GM")
    await step("GM gives Lyra money", invoke(inv.money_add, inv, as_(gm), amount=50, currency="Dukaten", character="Lyra"),
               r"Lyra\*\* bekommt \*\*50 Dukaten\*\* \(jetzt 50 Dukaten\)")
    await step("Spending without naming the currency", invoke(inv.money_spend, inv, as_(anna), amount=20),
               r"Lyra\*\* gibt \*\*20 Dukaten\*\* aus \(noch 30 Dukaten\)")
    await step("Can't spend more than you have", invoke(inv.money_spend, inv, as_(anna), amount=100),
               r"Nur 30 Dukaten vorhanden", "ephemeral")
    await step("Paying another character", invoke(inv.money_give, inv, as_(anna), amount=10, to="Grom"),
               r"Lyra\*\* gibt \*\*10 Dukaten\*\* an \*\*Grom\*\*")
    await step("Giving an item to the stash", invoke(inv.item_give, inv, as_(anna), name="seil", to=STASH),
               r"Lyra\*\* gibt \*\*Seil\*\* an das Gruppeninventar")
    await step("Taking it out of the stash", invoke(inv.item_take, inv, as_(ben), name="Seil"),
               r"Grom\*\* nimmt \*\*Seil\*\* aus dem Gruppeninventar \(noch 0\)")
    await step("…it's gone now", invoke(inv.item_take, inv, as_(ben), name="Seil"), "nicht gefunden", "ephemeral")
    await step("Stash money", invoke(inv.money_give, inv, as_(ben), amount=5, to=STASH), r"an das Gruppeninventar")
    await step("Looking into the stash", invoke(inv.inventory, inv, as_(ben), whose=STASH),
               r"Gruppeninventar.*3× Heiltrank.*Geld: 5 Dukaten")
    await step("Lyra's inventory", invoke(inv.inventory, inv, as_(anna)),
               r"Inventar von Lyra.*\*\*Seil\*\* · \*15 m\*.*Geld: 20 Dukaten")
    values = await autocomplete(inv.inventory, as_(anna), "whose", "")
    assert values[0] == STASH and "Grom" in values and "Lyra" in values, values
    assert await autocomplete(inv.money_add, as_(anna), "currency", "duk") == ["Dukaten"]
    assert await autocomplete(inv.item_take, as_(anna), "name", "") == ["Heiltrank"]
    assert await autocomplete(inv.item_remove, as_(anna), "name", "") == ["Seil"]

    # ---------------------------------------------------------------- character sheet card
    await step("Card colour", invoke(chars.char_color, chars, as_(anna), color="purple"), r"#9b59b6")
    await step("Unknown colour", invoke(chars.char_color, chars, as_(anna), color="sparkly"), "hex colour", "ephemeral")

    # profile & description
    assert (await autocomplete(chars.char_profile, as_(anna), "field", "aug")) == ["Augen"]
    await step("Profile field", invoke(chars.char_profile, chars, as_(anna), field="Alter", value="19"),
               r"Steckbrief von \*\*Lyra\*\*: \*\*Alter\*\* 19")
    await invoke(chars.char_profile, chars, as_(anna), field="Haare", value="lang,   silbern")
    await invoke(chars.char_profile, chars, as_(anna), field="Herkunft", value="Thorwal")
    await step("Updating a field ignores capitalisation", invoke(chars.char_profile, chars, as_(anna), field="alter",
                                                                  value="20"), r"\*\*Alter\*\* 20")
    await step("Removing a field", invoke(chars.char_profile, chars, as_(anna), field="Herkunft"),
               r"\*\*Herkunft\*\* aus dem Steckbrief von \*\*Lyra\*\* entfernt")
    await step("Removing a field that isn't there", invoke(chars.char_profile, chars, as_(anna), field="Augen"),
               r"hat kein Feld \*\*Augen\*\*", "ephemeral")
    inter = as_(anna)
    await invoke(chars.char_description, chars, inter)
    await step("Description", submit_modal(inter.modal, as_(anna), text="Eine Elfe mit Ziel.\nUnd mit Seil."),
               r"Beschreibung von \*\*Lyra\*\* gespeichert")
    await step("Players can't lay out the sheet", invoke(camp.sheet, camp, as_(anna)), "Only the GM")
    inter = as_(gm)
    await invoke(camp.sheet, camp, inter)
    await step("A broken layout is explained", submit_modal(inter.modal, as_(gm), layout="Eigenschaften mu, ge"),
               "needs the form")
    inter = as_(gm)
    await invoke(camp.sheet, camp, inter)
    await step("GM lays out the sheet for their game",
               submit_modal(inter.modal, as_(gm), layout="Eigenschaften: MU=mu, GE=ge\nKampf: LeP=max_hp"),
               r"Bogen-Layout für \*\*Das Schwarze Auge\*\* gespeichert")
    out = await step("The card follows the layout", invoke(chars.char_show, chars, as_(anna)),
                     r"Charakterbogen · gespielt von Anna.*\*\*Lyra\*\*.*▰+ \*\*20\*\*/20\n\s*0 EP"
                     r"\n\s*\n\s*> Eine Elfe mit Ziel\.\n\s*> Und mit Seil\."
                     r".*Steckbrief: `Alter` 20\n\s*`Haare` lang, silbern"
                     r".*Eigenschaften: `MU` \*\*12\*\*\n\s*`GE` \*\*14\*\*.*Kampf: `LeP` \*\*20\*\*"
                     r".*Weitere: `KK   ` \*\*11\*\*\n\s*`Level` \*\*1\*\*.*Inventar: • \*\*Seil\*\* · \*15 m\*.*20 Dukaten")
    assert out[0].embeds[0].color.value == 0x9B59B6
    await step("Back to the automatic layout", invoke(camp.sheet, camp, as_(gm), reset=True), "wieder automatisch")

    # ---------------------------------------------------------------- export & import keep the inventory
    out = await step("Export Lyra", invoke(chars.char_export, chars, as_(anna)), "Lyra")
    data = json.loads(out[0].file.fp.read())
    assert data["items"] == [{"name": "Seil", "qty": 1, "note": "15 m"}] and data["money"] == {"Dukaten": 20}
    assert data["color"] == 0x9B59B6
    assert data["profile"] == [["Alter", "20"], ["Haare", "lang, silbern"]]
    assert data["bio"] == "Eine Elfe mit Ziel.\nUnd mit Seil."
    await invoke(chars.char_import, chars, as_(ben), file=FakeAttachment("Lyra.json", json.dumps(data).encode()),
                 name="Lyra II")
    await step("The copy has the inventory too", invoke(inv.inventory, inv, as_(ben), whose="Lyra II"),
               r"Inventar von Lyra II.*Seil.*20 Dukaten")

    await step("Back to English", invoke(camp.language, camp, as_(gm), language=Choice(name="English", value="en")),
               r"This campaign now speaks \*\*English\*\*")
    await step("English again", invoke(inv.inventory, inv, as_(ben), whose=STASH), r"Party stash.*Money: 5 Dukaten")


def test_phase5_session(tmp_path):
    asyncio.run(run(str(tmp_path / "phase5.db")))


if __name__ == "__main__":
    import tempfile
    VERBOSE = True
    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(f"{d}/phase5.db"))
