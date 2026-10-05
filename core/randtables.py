"""
Random tables.

Entry syntax (one entry per line, or separated by ';' in a single-line command):
    3* A pack of wolves          weight 3 (default 1)
    [[2d6]] goblins              inline roll, replaced by its total
    {loot}                       rolls on another table (nested up to 5 levels)
"""
from __future__ import annotations

import random
import re
from typing import Awaitable, Callable, Optional

from dice.engine import DiceError, roll

MAX_ENTRIES = 300
MAX_ENTRY_LEN = 300
MAX_DEPTH = 5

_rng = random.SystemRandom()
_WEIGHT_RE = re.compile(r"^\s*(\d{1,3})\s*\*\s*(.+)$")
_INLINE_RE = re.compile(r"\[\[(.+?)\]\]")
_REF_RE = re.compile(r"\{([A-Za-z0-9_ \-]{1,32})\}")

Entries = list[list]  # [[weight, text], ...]
Resolver = Callable[[str], Awaitable[Optional[Entries]]]


class TableError(DiceError):
    pass


def parse_entries(text: str) -> Entries:
    lines = text.split("\n") if "\n" in text else text.split(";")
    entries = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        weight = 1
        m = _WEIGHT_RE.match(line)
        if m:
            weight, line = int(m.group(1)), m.group(2).strip()
        if weight < 1:
            raise TableError(f"Weight must be at least 1: `{raw.strip()}`")
        if len(line) > MAX_ENTRY_LEN:
            raise TableError(f"Entries can be at most {MAX_ENTRY_LEN} characters.")
        entries.append([weight, line])
    if not entries:
        raise TableError("The table needs at least one entry.")
    if len(entries) > MAX_ENTRIES:
        raise TableError(f"Tables can have at most {MAX_ENTRIES} entries.")
    for _, t in entries:  # validate inline rolls now, not at the table
        for expr in _INLINE_RE.findall(t):
            roll(expr)
    return entries


def format_entries(entries: Entries) -> str:
    return "\n".join(f"{w}* {t}" if w != 1 else t for w, t in entries)


def pick(entries: Entries) -> str:
    return _rng.choices([t for _, t in entries], weights=[w for w, _ in entries], k=1)[0]


async def roll_on(entries: Entries, resolver: Resolver, depth: int = 0) -> str:
    """Pick an entry and expand its inline rolls and {table} references."""
    text = pick(entries)

    text = _INLINE_RE.sub(lambda m: str(roll(m.group(1)).total), text)

    if depth >= MAX_DEPTH:
        return _REF_RE.sub(lambda m: m.group(1), text)
    parts, last = [], 0
    for m in _REF_RE.finditer(text):
        parts.append(text[last:m.start()])
        sub = await resolver(m.group(1).strip())
        parts.append(await roll_on(sub, resolver, depth + 1) if sub else f"{{{m.group(1)}?}}")
        last = m.end()
    parts.append(text[last:])
    return "".join(parts)


# --------------------------------------------------------------------------- built-in generators
# Every campaign can use these; a campaign table with the same name overrides one.

def _e(*items: str) -> Entries:
    return [[1, i] for i in items]


BUILTIN: dict[str, Entries] = {
    "first_name": _e(
        "Aldric", "Bryn", "Cassia", "Dorian", "Elowen", "Fenwick", "Garrick", "Hilde", "Ivo", "Jessamy",
        "Kael", "Liora", "Magnus", "Nessa", "Orrin", "Perrin", "Quilla", "Rowan", "Sabine", "Tobias",
        "Ulla", "Vesper", "Wren", "Yorick", "Zara", "Agnes", "Bertram", "Corwin", "Darya", "Edda"),
    "last_name": _e(
        "Ashdown", "Blackwood", "Copperkettle", "Dunmore", "Eversong", "Fairweather", "Grimsby", "Hollowell",
        "Ironside", "Juniper", "Kettleburn", "Larkspur", "Mossbottom", "Nettleby", "Oakheart", "Pennywhistle",
        "Quickfoot", "Ravensworth", "Stonebridge", "Thistlewood", "Underhill", "Vale", "Whitlock", "Yarrow"),
    "name": _e("{first_name} {last_name}"),
    "trait": _e(
        "nervous", "cheerful", "suspicious", "pompous", "absent-minded", "gruff", "overly friendly", "cowardly",
        "boastful", "melancholic", "greedy", "pious", "flirtatious", "paranoid", "honest to a fault", "sly",
        "exhausted", "superstitious", "curious", "bitter"),
    "occupation": _e(
        "blacksmith", "innkeeper", "fence", "priest", "guard captain", "herbalist", "tax collector", "bard",
        "fisher", "noble's servant", "gravedigger", "alchemist", "merchant", "ratcatcher", "scribe",
        "retired adventurer", "farmer", "smuggler", "cartographer", "town crier"),
    "quirk": _e(
        "hums constantly", "collects teeth", "owes money to the wrong people", "is secretly a spy",
        "never makes eye contact", "speaks in the third person", "has a pet rat named Lord Whiskers",
        "is convinced the party are someone else", "lies about everything except prices",
        "is looking for a lost sibling", "tells terrible jokes", "keeps a detailed diary of everyone",
        "is allergic to magic", "wants to become an adventurer", "knows a secret about the mayor",
        "talks to their dead spouse", "only trades in favors", "is hiding a fresh wound"),
    "npc": _e("**{name}**, a {trait} {occupation} who {quirk}."),
    "tavern_adj": _e(
        "Prancing", "Drunken", "Golden", "Rusty", "Sleeping", "Laughing", "Crooked", "Silver", "One-Eyed",
        "Wandering", "Howling", "Gilded", "Soggy", "Grinning", "Lucky"),
    "tavern_noun": _e(
        "Pony", "Dragon", "Goose", "Tankard", "Wizard", "Boar", "Mermaid", "Anchor", "Griffin", "Barrel",
        "Lantern", "Badger", "Kettle", "Crown", "Owl"),
    "tavern": _e("**The {tavern_adj} {tavern_noun}**, run by {name}, a {trait} host."),
    "loot": [
        [6, "[[3d6]] copper and [[1d6]] silver coins"],
        [4, "[[2d10]] gold coins"],
        [3, "a {trait} merchant's ledger worth [[1d4*10]] gold to the right person"],
        [3, "a potion of healing"],
        [2, "a silver ring set with a small gem ([[2d4*10]] gp)"],
        [2, "a map to {tavern}"],
        [1, "a mysterious key that fits no lock in town"],
        [1, "a minor magic item (GM's choice)"],
    ],
    "weather": [
        [4, "clear skies and a light breeze"],
        [3, "overcast and cool"],
        [2, "drizzle all day"],
        [2, "thick fog until noon"],
        [1, "a thunderstorm rolls in by evening"],
        [1, "oppressive heat"],
        [1, "strong winds, hard to hear each other"],
        [1, "an eerie stillness, no birds sing"],
    ],
    "complication": _e(
        "an old rival shows up", "the bridge is out", "a storm forces everyone indoors",
        "someone is following the party", "the contact is already dead", "the price has doubled",
        "a guard recognizes one of the party", "a fire breaks out nearby", "the map is wrong",
        "a child asks the party for help", "an ally betrays them", "the weather turns: {weather}"),
}

GENERATORS = ["npc", "name", "tavern", "loot", "weather", "complication"]
