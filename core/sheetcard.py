"""
The character sheet card (/char show).

The GM can lay out the sheet for their game with `/campaign sheet`, one section per line:

    Attributes: str, dex, con, int, wis, cha
    Combat: max_hp, ac, initiative
    Talents: Climbing=climb, Stealth=stealth

Entries are stats or skills; `Label=name` shows a custom label. Stats and skills that aren't in the layout
still appear (under "More" and "Skills"), so nothing ever disappears from a sheet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import discord

from dice.engine import DiceError, split_label, validate_name

from .db import Character, Item
from .helpers import COLOR_INFO, UserError
from .i18n import t
from .inventory import fmt_money, item_lines
from .sheet import Sheet

MAX_SECTIONS = 12
MAX_ENTRIES = 30
CARD_ITEMS = 10
EXAMPLE_LAYOUT = ("Attributes: str, dex, con, int, wis, cha\n"
                  "Combat: max_hp, ac, initiative\n"
                  "Talents: Climbing=climb, Stealth=stealth")

Layout = list[tuple[str, list[tuple[str, str]]]]  # [(section title, [(label, stat or skill name)])]


def default_label(name: str) -> str:
    """'str' -> 'STR', 'max_hp' -> 'Max HP', 'stealth' -> 'Stealth'"""
    if len(name) <= 3:
        return name.upper()
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in name.split("_") if w)


def parse_layout(text: str) -> Layout:
    """Parse the GM's layout text, or raise UserError explaining what's wrong."""
    sections: Layout = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise UserError(f"`{line[:60]}` needs the form `Section: stat, stat`, e.g. `Attributes: str, dex`.")
        title, rest = line.split(":", 1)
        title = " ".join(title.split())[:60]
        if not title:
            raise UserError(f"`{line[:60]}` has no section name before the `:`.")
        entries = []
        for part in rest.split(","):
            part = part.strip()
            if not part:
                continue
            label, _, name = part.rpartition("=")
            try:
                name = validate_name(name, "stat or skill name")
            except DiceError as e:
                raise UserError(f"Section **{title}**: {e}")
            entries.append(((" ".join(label.split()) or default_label(name))[:24], name))
        if len(entries) > MAX_ENTRIES:
            raise UserError(f"Section **{title}** has more than {MAX_ENTRIES} entries.")
        sections.append((title, entries))
    if not sections:
        raise UserError("The layout is empty. Example:\n```\n" + EXAMPLE_LAYOUT + "\n```")
    if len(sections) > MAX_SECTIONS:
        raise UserError(f"A sheet can have at most {MAX_SECTIONS} sections.")
    return sections


@dataclass
class CardData:
    """Everything the card shows, collected by the caller (see cogs/characters.py)."""
    character: Character
    owner_name: str
    sheet: Sheet
    lang: str = "en"
    layout: Optional[str] = None
    hp: Optional[int] = None
    max_hp: Optional[int] = None
    temp_hp: int = 0
    conditions: list[str] = field(default_factory=list)
    xp_text: Optional[str] = None
    resources: list[tuple[str, int, object]] = field(default_factory=list)   # (name, current, max or '?')
    items: list[Item] = field(default_factory=list)
    money: dict[str, int] = field(default_factory=dict)
    companions: list[str] = field(default_factory=list)
    parent: Optional[str] = None


def _bar(current: int, maximum, width: int = 10) -> str:
    if not isinstance(maximum, int) or maximum <= 0:
        return ""
    filled = max(0, min(width, round(width * current / maximum)))
    if current > 0 and filled == 0:
        filled = 1
    return "▰" * filled + "▱" * (width - filled) + " "


def _value(sheet: Sheet, name: str) -> Optional[str]:
    """A stat's value, or a skill's: its number (if it's dice-free) or its formula. None if neither exists."""
    if name in sheet.stats:
        try:
            return str(sheet.resolve(name))
        except DiceError:
            return ""
    skill = sheet.skills.get(name)
    if not skill:
        return None
    if skill.kind == "3d20":
        return f"{'/'.join(a.upper() for a in skill.attributes or [])} · {skill.points}"
    formula = split_label(skill.formula)[0]
    try:
        return str(sheet.resolve_formula(formula))
    except DiceError:
        return f"`{formula}`"


def _lines(entries: list[tuple[str, str]], sheet: Sheet) -> list[str]:
    width = min(12, max((len(label) for label, _ in entries), default=0))
    out = []
    for label, name in entries:
        value = _value(sheet, name)
        if value is None:
            value = "—"
        elif not value.startswith("`"):  # formulas are already in a code box
            value = f"**{value}**"
        out.append(f"`{label:<{width}}` {value}")
    return out


GRID_AFTER = 6    # sections with more entries than this are split into columns
GRID_COLUMNS = 3  # Discord shows at most three inline fields side by side
BLANK = "​"  # an empty field name/value


class _Fields:
    """Adds embed fields and keeps track of the current row, so a grid always starts on a row of its own."""

    def __init__(self, embed: discord.Embed):
        self.e, self.in_row = embed, 0

    def add(self, name: str, value: str, inline: bool):
        self.e.add_field(name=name, value=value[:1024] or BLANK, inline=inline)
        self.in_row = (self.in_row + 1) % GRID_COLUMNS if inline else 0

    def new_row(self):
        if self.in_row:
            self.add(BLANK, BLANK, inline=False)

    def section(self, title: str, entries: list[tuple[str, str]], sheet: Sheet):
        """Stats/skills: a short section is one column; a long one becomes a grid, read column by column."""
        self.grid(title, entries, lambda chunk: _lines(chunk, sheet))

    def grid(self, title: str, entries: list, render):
        if len(entries) <= GRID_AFTER:
            self.add(title, "\n".join(render(entries)), inline=True)
            return
        self.new_row()
        per = -(-len(entries) // GRID_COLUMNS)  # rounded up
        for i in range(GRID_COLUMNS):
            chunk = entries[i * per:(i + 1) * per]
            if chunk:
                self.add(title if i == 0 else BLANK, "\n".join(render(chunk)), inline=True)
        self.in_row = 0  # the grid filled its row


PROFILE_COLUMN = 22  # longest profile line that still fits in a grid column without wrapping


def _profile_width(pairs: list) -> int:
    return min(12, max((len(k) for k, _ in pairs), default=0))


def _profile_lines(pairs: list, width: int) -> list[str]:
    return [f"`{k:<{width}}` {v}" for k, v in pairs]


def _chunks(lines: list[str], limit: int = 1024) -> list[str]:
    chunks, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += line[:limit] + "\n"
    if cur:
        chunks.append(cur)
    return chunks


def build_card(d: CardData) -> discord.Embed:
    c, sheet, lang = d.character, d.sheet, d.lang
    e = discord.Embed(title=c.name, color=c.color if c.color is not None else COLOR_INFO)
    e.set_author(name=t(lang, "Character sheet · played by {owner}", owner=d.owner_name))
    if c.avatar_url:
        e.set_thumbnail(url=c.avatar_url)

    # Header: health, level, conditions
    head = []
    if d.parent:
        head.append(t(lang, "Companion of **{name}**", name=d.parent))
    if d.hp is not None or d.max_hp is not None:
        hp = d.hp if d.hp is not None else d.max_hp
        line = f"{_bar(hp, d.max_hp)}**{hp}**" + (f"/{d.max_hp}" if d.max_hp else "")
        if d.temp_hp:
            line += " · " + t(lang, "+{n} temporary", n=d.temp_hp)
        head.append(line)
    if d.xp_text:
        head.append(f"{d.xp_text}")
    if d.conditions:
        head.append(", ".join(d.conditions))
    if c.bio:
        head.append(("\n" if head else "") + "\n".join(f"> {line}" if line else ">" for line in c.bio.splitlines()))
    e.description = "\n".join(head)[:4000] or None

    fields = _Fields(e)
    if c.profile:
        # One label width for the whole profile, so every column lines up. Short details become a grid;
        # if one is too long for a grid column, the profile is a single full-width list instead.
        width = _profile_width(c.profile)
        if all(width + 1 + len(v) <= PROFILE_COLUMN for _, v in c.profile):
            fields.grid(t(lang, "Profile"), c.profile, lambda chunk: _profile_lines(chunk, width))
        else:
            for i, chunk in enumerate(_chunks(_profile_lines(c.profile, width))[:3]):
                fields.add(t(lang, "Profile") if i == 0 else BLANK, chunk, inline=False)
        fields.new_row()

    # Stat sections: the GM's layout, then everything it doesn't mention
    shown: set[str] = set()
    sections = parse_layout(d.layout) if d.layout else []
    for title, entries in sections:
        shown.update(name for _, name in entries)
        if entries:
            fields.section(title, entries, sheet)
    rest = [n for n in sheet.stats if n not in shown]
    if sections:
        if rest:
            fields.section(t(lang, "More"), [(default_label(n), n) for n in rest], sheet)
    else:
        base = [n for n in rest if not sheet.is_derived(n)]
        derived = [n for n in rest if sheet.is_derived(n)]
        for title, names in ((t(lang, "Stats"), base), (t(lang, "Derived"), derived)):
            if names:
                fields.section(title, [(default_label(n), n) for n in names], sheet)
    if not sheet.stats:
        fields.add(t(lang, "Stats"), t(lang, "*none yet: `/stat set`*"), inline=False)

    # Skills not already in the layout: a grid when the values are short (like dice counts),
    # a full-width list when they're longer formulas
    skills = [s for s in sheet.skills.values() if s.name not in shown]
    if skills:
        entries = [(default_label(s.name), s.name) for s in skills]
        if all(len(_value(sheet, s.name) or "") <= 8 for s in skills):
            fields.new_row()
            fields.section(t(lang, "Skills"), entries, sheet)
        else:
            for i, chunk in enumerate(_chunks(_lines(entries, sheet))[:3]):
                fields.add(t(lang, "Skills") if i == 0 else BLANK, chunk, inline=False)

    if d.resources:
        lines = [f"`{name}` {_bar(cur, mx, 6)}**{cur}**/{mx}" for name, cur, mx in d.resources]
        fields.add(t(lang, "Resources"), "\n".join(lines), inline=False)

    if d.items or d.money:
        lines = item_lines(d.items, lang, CARD_ITEMS) if d.items else []
        if d.money:
            lines.append(fmt_money(d.money))
        fields.add(t(lang, "Inventory"), "\n".join(lines), inline=False)

    if d.companions:
        fields.add(t(lang, "Companions"), ", ".join(d.companions), inline=False)

    # Discord allows 6000 characters per embed: drop the last fields if a huge sheet gets too long
    while len(e) > 5900 and len(e.fields) > 1:
        e.remove_field(len(e.fields) - 1)
    e.set_footer(text=t(lang, "/stat set · /skill add · /item add · /char color · Layout: /campaign sheet"))
    return e
