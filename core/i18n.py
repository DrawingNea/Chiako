"""
Translations of what the bot says, per campaign (`/campaign language`).

The English text is the key: t(lang, "Results for {name}", name="Lyra"). Text without a translation
falls back to English, so nothing breaks when a string is missing.
"""
from __future__ import annotations

LANGUAGES = {"en": "English", "de": "Deutsch"}

DE: dict[str, str] = {
    # ---------------------------------------------------------------- roll cards
    "Results for {name}": "Ergebnis für {name}",
    "{n} × {sides}-sided die": "{n} × W{sides}",
    "{n} × {sides}-sided dice": "{n} × W{sides}",
    "{n} × Fate die": "{n} × Fate-Würfel",
    "{n} × Fate dice": "{n} × Fate-Würfel",
    "1 × 20-sided die with advantage": "1 × W20 mit Vorteil",
    "1 × 20-sided die with disadvantage": "1 × W20 mit Nachteil",
    "keep highest {n}": "die höchsten {n} zählen",
    "keep lowest {n}": "die niedrigsten {n} zählen",
    "drop highest {n}": "die höchsten {n} streichen",
    "drop lowest {n}": "die niedrigsten {n} streichen",
    "reroll 1s once": "1er einmal neu würfeln",
    "reroll ≤ {n} once": "≤ {n} einmal neu würfeln",
    "{sides}s explode": "{sides}er explodieren",
    "{n}+ explode": "ab {n} explodiert",
    "success at {rule} {target}": "Erfolg bei {rule} {target}",
    "≤ {n} cancels one": "≤ {n} hebt einen Erfolg auf",
    "{n} Success": "{n} Erfolg",
    "{n} Successes": "{n} Erfolge",
    "No successes": "Keine Erfolge",
    "Botch ({n})": "Patzer ({n})",
    "{n} bonus die from explosions": "{n} Bonuswürfel durch Explosionen",
    "{n} bonus dice from explosions": "{n} Bonuswürfel durch Explosionen",
    "Natural 20!": "Natürliche 20!",
    "Natural 1!": "Natürliche 1!",
    "(no single d20 found, so advantage/disadvantage was ignored)":
        "(kein einzelner W20 gefunden, Vorteil/Nachteil wurde ignoriert)",
    "Strong hit": "Voller Erfolg",
    "Weak hit": "Teilerfolg",
    "Miss": "Fehlschlag",
    # Fate ladder
    "Legendary": "Legendär", "Epic": "Episch", "Fantastic": "Fantastisch", "Superb": "Hervorragend",
    "Great": "Großartig", "Good": "Gut", "Fair": "Ordentlich", "Average": "Durchschnittlich",
    "Mediocre": "Mäßig", "Poor": "Schwach", "Terrible": "Schrecklich", "Catastrophic": "Katastrophal",
    "Horrifying": "Entsetzlich",
    # 3d20 (DSA)
    "{points} skill points": "{points} FP",
    "modifier {mod}": "Modifikator {mod}",
    "Botch!": "Patzer!",
    "Critical success! QL {ql}": "Kritischer Erfolg! QS {ql}",
    "Success · QL {ql}": "Gelungen · QS {ql}",
    "{n} point left": "{n} Punkt übrig",
    "{n} points left": "{n} Punkte übrig",
    "Failed by {n}": "Misslungen um {n}",
    "3d20 check": "3W20-Probe",

    # ---------------------------------------------------------------- rolling & chat
    "**{who}** made a secret roll… only the GM knows the result.":
        "**{who}** hat geheim gewürfelt… nur die SL kennt das Ergebnis.",
    "Secret roll from **{who}** in {channel}": "Geheimer Wurf von **{who}** in {channel}",
    "Sent to the GM.": "An die SL geschickt.",
    "Talk to me to roll: {me} `roll shooting & dex` · {me} `check 10` · {me} `w5` · {me} `2d6+3` · {me} `pool(7)`":
        "Sprich mich an, um zu würfeln: {me} `würfel schiessen & ge` · {me} `probe 10` · {me} `w5` · "
        "{me} `2w6+3` · {me} `pool(7)`",
    "Works in other languages too: `würfel auf schiessen und ge` · `lance 5` · `tira 5`":
        "Klappt auch auf Englisch & Co.: `roll shooting & dex` · `lance 5` · `tira 5`",
    "Everything else is in `/help`.": "Alles andere steht in `/help`.",
    "`{n}` dice need the campaign's dice rules, and this channel has none yet. "
    "The GM can set them with `/campaign dice`, or roll e.g. `{n}d10`.":
        "`{n}` Würfel brauchen die Würfelregeln der Kampagne, und hier gibt es noch keine. "
        "Die SL legt sie mit `/campaign dice` fest, oder würfle z. B. `{n}d10`.",

    # ---------------------------------------------------------------- campaign dice rules
    "d{sides}": "W{sides}",
    "success at ≥ {n}": "Erfolg ab {n}",
    "dice are added up": "Würfel werden addiert",
    "≤ {n} cancels a success": "≤ {n} hebt einen Erfolg auf",
    "Dice rules · {campaign}": "Würfelregeln · {campaign}",
    "A skill whose value is a number rolls that many dice, e.g. `/skill add shooting 5`.":
        "Eine Fertigkeit mit einer Zahl als Wert würfelt so viele Würfel, z. B. `/skill add schiessen 5`.",
    "**Roll:** `/check shooting` · `/check shooting & dex` · `/check 5`":
        "**Würfeln:** `/check schiessen` · `/check schiessen & ge` · `/check 5`",
    "**Or just talk to the bot:** {me} `roll shooting & dex` · {me} `w5`":
        "**Oder sprich einfach mich an:** {me} `würfel schiessen & ge` · {me} `w5`",
    "No dice rules yet: `/check` rolls skill formulas as written.\n"
    "The GM can set them up, e.g. `/campaign dice sides:10 success:8 explode:10`.":
        "Noch keine Würfelregeln: `/check` würfelt Fertigkeiten so, wie sie eingetragen sind.\n"
        "Die SL legt sie fest, z. B. `/campaign dice sides:10 success:8 explode:10`.",
    "Dice rules are off: `/check` rolls skill formulas as written again.":
        "Würfelregeln sind aus: `/check` würfelt Fertigkeiten wieder so, wie sie eingetragen sind.",

    # ---------------------------------------------------------------- language
    "This campaign now speaks **{language}**.": "Diese Kampagne spricht jetzt **{language}**.",

    # ---------------------------------------------------------------- scheduling
    "The session": "Die Spielrunde",
    "Tomorrow is session day!": "Morgen ist Spieltag!",
    "Session today!": "Heute ist Spieltag!",
    "Session {day}!": "Spielrunde {day}!",
    "on {weekday}": "am {weekday}",
    "**{headline}** {name} starts {when}.": "**{headline}** {name} beginnt {when}.",
    "{name} starts {when}!": "{name} beginnt {when}!",
    "**Game time!** {name} starts now!": "**Los geht's!** {name} beginnt jetzt!",
    "Next session": "Nächste Spielrunde",
    "I'll remind everyone an hour before.": "Ich erinnere alle eine Stunde vorher.",
    "I'll remind everyone the day before and an hour before.":
        "Ich erinnere alle am Tag vorher und eine Stunde vorher.",
    "The session on {when} is cancelled.": "Die Spielrunde am {when} fällt aus.",
    "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch", "Thursday": "Donnerstag",
    "Friday": "Freitag", "Saturday": "Samstag", "Sunday": "Sonntag",

    # ---------------------------------------------------------------- inventory & money
    "the party stash": "das Gruppeninventar",
    "Party stash": "Gruppeninventar",
    "{who} gets **{item}** (now {n}).": "{who} bekommt **{item}** (jetzt {n}).",
    "{who} loses **{item}** ({n} left).": "{who} verliert **{item}** (noch {n}).",
    "{who} has no **{item}**.": "**{item}** nicht gefunden ({who}).",
    "{who} only has **{item}**.": "Nur **{item}** vorhanden ({who}).",
    "**{giver}** gives **{item}** to {target}.": "**{giver}** gibt **{item}** an {target}.",
    "**{taker}** takes **{item}** from the party stash ({n} left).":
        "**{taker}** nimmt **{item}** aus dem Gruppeninventar (noch {n}).",
    "{who} gets **{money}** (now {total}).": "{who} bekommt **{money}** (jetzt {total}).",
    "{who} only has {money}.": "Nur {money} vorhanden ({who}).",
    "{who} spends **{money}** ({left} left).": "{who} gibt **{money}** aus (noch {left}).",
    "**{giver}** gives **{money}** to {target}.": "**{giver}** gibt **{money}** an {target}.",
    "**{taker}** takes **{money}** from the party stash ({left} left).":
        "**{taker}** nimmt **{money}** aus dem Gruppeninventar (noch {left}).",
    "Inventory of {name}": "Inventar von {name}",
    "Money": "Geld",
    "*No items yet.*": "*Noch keine Gegenstände.*",
    "…and {n} more": "…und {n} weitere",

    # ---------------------------------------------------------------- character sheet card
    "Character sheet · played by {owner}": "Charakterbogen · gespielt von {owner}",
    "Companion of **{name}**": "Begleiter von **{name}**",
    "+{n} temporary": "+{n} temporär",
    "{xp} XP": "{xp} EP",
    "{xp} XP · level {lvl} (max)": "{xp} EP · Stufe {lvl} (max)",
    "{xp} XP · level {lvl} · {bar} {left} to level {next}": "{xp} EP · Stufe {lvl} · {bar} noch {left} bis Stufe {next}",
    "More": "Weitere",
    "Stats": "Werte",
    "Derived": "Abgeleitet",
    "*none yet: `/stat set`*": "*noch keine: `/stat set`*",
    "Skills": "Fertigkeiten",
    "Resources": "Ressourcen",
    "Inventory": "Inventar",
    "Companions": "Begleiter",
    "/stat set · /skill add · /item add · /char color · Layout: /campaign sheet":
        "/stat set · /skill add · /item add · /char color · Bogen-Layout: /campaign sheet",
    "Sheet layout saved for **{campaign}**. Have a look with `/char show`.":
        "Bogen-Layout für **{campaign}** gespeichert. Schau es dir mit `/char show` an.",
    "The sheet layout is back to automatic.": "Der Charakterbogen ordnet sich wieder automatisch.",

    # ---------------------------------------------------------------- /help
    "Choose a chapter…": "Kapitel wählen…",
    "Back": "Zurück",
    "Next": "Weiter",
    "Chapter {n} of {total} · pick another one in the menu below":
        "Kapitel {n} von {total} · ein anderes findest du im Menü unten",
}

STRINGS = {"de": DE}


def t(lang: str, text: str, **kwargs) -> str:
    """Translate `text` (English) into `lang` and fill in {placeholders}."""
    out = STRINGS.get(lang or "en", {}).get(text, text)
    return out.format(**kwargs) if kwargs else out


def plural(lang: str, n: int, one: str, many: str, **kwargs) -> str:
    """t() with the singular or plural English key, e.g. plural(lang, 2, '{n} Success', '{n} Successes')."""
    return t(lang, one if n == 1 else many, n=n, **kwargs)
