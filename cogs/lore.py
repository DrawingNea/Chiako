"""Random tables (/table), generators (/generate) and campaign notes (/note)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.db import Campaign, Note
from core.helpers import COLOR_INFO, BaseView, UserError, get_campaign, is_gm, require_campaign, require_gm
from core.achievements import notify
from core.randtables import BUILTIN, GENERATORS, format_entries, parse_entries, roll_on

TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_ \-]{1,32}$")
CATEGORIES = ["NPC", "Place", "Quest", "Item", "Faction", "Lore", "Session"]
GM_ONLY = " · *GM only*"


def table_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not TABLE_NAME_RE.match(name):
        raise UserError("Table names: letters, digits, spaces, `_` and `-`, max 32 characters.")
    return name


def note_embed(note: Note) -> discord.Embed:
    e = discord.Embed(title=note.title,
                      description=f"{note.content[:3900]}\n\n-# <@{note.author_id}>",
                      color=discord.Color.dark_grey() if note.gm_only else COLOR_INFO,
                      timestamp=datetime.fromtimestamp(note.updated_at, tz=timezone.utc))
    e.set_footer(text=f"{note.category}{' · GM only' if note.gm_only else ''} · last edited")
    return e


# --------------------------------------------------------------------------- modals

class TableModal(discord.ui.Modal):
    def __init__(self, cog: "Lore", campaign: Campaign, name: str, existing: str = ""):
        super().__init__(title=f"Table: {name}"[:45])
        self.cog, self.campaign, self.name = cog, campaign, name
        self.entries = discord.ui.TextInput(
            label="One entry per line ('3* text' = weight 3)", style=discord.TextStyle.paragraph,
            default=existing[:4000] or None, max_length=4000,
            placeholder="A pack of [[1d4+1]] wolves\n2* A lost merchant\nRoll again on {weather}")
        self.add_item(self.entries)

    async def on_submit(self, interaction: discord.Interaction):
        entries = parse_entries(self.entries.value)
        await self.cog.db.save_table(self.campaign.id, self.name, entries)
        await interaction.response.send_message(
            f"Table **{self.name}** saved with {len(entries)} entries. Roll it with `/table roll {self.name}`.",
            ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        from core.helpers import report_error
        await report_error(interaction, error)


class NoteModal(discord.ui.Modal):
    def __init__(self, cog: "Lore", campaign: Campaign, title: str, category: str, gm_only: bool,
                 author_id: int, existing: str = ""):
        super().__init__(title=f"Note: {title}"[:45])
        self.cog, self.campaign, self.note_title = cog, campaign, title
        self.category, self.gm_only, self.author_id = category, gm_only, author_id
        self.content = discord.ui.TextInput(label="Text", style=discord.TextStyle.paragraph,
                                            default=existing[:4000] or None, max_length=4000)
        self.add_item(self.content)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.save_note(interaction, self.campaign, self.note_title, self.category, self.gm_only,
                                 self.content.value, self.author_id)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        from core.helpers import report_error
        await report_error(interaction, error)


class ConfirmDelete(BaseView):
    def __init__(self, owner_id: int, action, label: str):
        super().__init__(timeout=60)
        self.owner_id, self.action, self.label = owner_id, action, label

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your call.", ephemeral=True)
            return
        await self.action()
        await interaction.response.edit_message(content=f"{self.label} deleted.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Nothing was deleted.", view=None)
        self.stop()


# --------------------------------------------------------------------------- cog

class Lore(commands.Cog):
    table = app_commands.Group(name="table", description="Random tables", guild_only=True)
    note = app_commands.Group(name="note", description="Campaign notes: NPCs, places, quests, lore",
                              guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------------ table helpers

    def _resolver(self, campaign: Optional[Campaign]):
        async def resolve(name: str):
            if campaign:
                found = await self.db.get_table(campaign.id, name)
                if found:
                    return found[1]
            return BUILTIN.get(name.lower().replace(" ", "_"))
        return resolve

    async def _roll_many(self, campaign, name: str, count: int) -> tuple[str, list[str]]:
        resolve = self._resolver(campaign)
        entries = await resolve(name)
        if not entries:
            raise UserError(f"No table called **{name}**. See `/table list`.")
        display = name.replace("_", " ").title()
        if campaign and (found := await self.db.get_table(campaign.id, name)):
            display = found[0]
        return display, [await roll_on(entries, resolve) for _ in range(count)]

    async def table_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        names = [n for n, _ in await self.db.list_tables(campaign.id)] if campaign else []
        names += [b for b in BUILTIN if b not in {n.lower() for n in names}]
        return [Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def own_table_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        return [Choice(name=f"{n} ({k} entries)", value=n) for n, k in await self.db.list_tables(campaign.id)
                if current.lower() in n.lower()][:25]

    # ------------------------------------------------------------------ /table

    @table.command(name="create", description="Create or replace a random table (GM). Leave entries empty for an editor")
    @app_commands.describe(name="Table name", entries="Optional: entries separated by ';' (or use the editor)")
    async def table_create(self, interaction: discord.Interaction, name: str, entries: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        name = table_name(name)
        if entries is None:
            await interaction.response.send_modal(TableModal(self, campaign, name))
            return
        parsed = parse_entries(entries)
        await self.db.save_table(campaign.id, name, parsed)
        await interaction.response.send_message(
            f"Table **{name}** saved with {len(parsed)} entries.", ephemeral=True)

    @table.command(name="edit", description="Edit a table in a text editor (GM)")
    async def table_edit(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        found = await self.db.get_table(campaign.id, name.strip())
        if found:
            real_name, entries = found
        elif name.strip().lower() in BUILTIN:  # start from a built-in to customise it
            real_name, entries = name.strip().lower(), BUILTIN[name.strip().lower()]
        else:
            raise UserError(f"No table **{name}**.")
        await interaction.response.send_modal(TableModal(self, campaign, real_name, format_entries(entries)))

    @table.command(name="add", description="Add one entry to a table (GM)")
    @app_commands.describe(entry="Text, may include [[dice]] and {other_table}", weight="How likely (default 1)")
    async def table_add(self, interaction: discord.Interaction, name: str, entry: str,
                        weight: app_commands.Range[int, 1, 999] = 1):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        found = await self.db.get_table(campaign.id, name.strip())
        real_name, entries = found if found else (table_name(name), [])
        new = parse_entries(f"{weight}* {entry}")
        await self.db.save_table(campaign.id, real_name, parse_entries(format_entries(entries + new)))
        await interaction.response.send_message(
            f"Added to **{real_name}** ({len(entries) + 1} entries).", ephemeral=True)

    @table.command(name="roll", description="Roll on a table (yours or a built-in like npc, loot, weather)")
    @app_commands.describe(count="How many results", private="Only you see the result")
    async def table_roll(self, interaction: discord.Interaction, name: str,
                         count: app_commands.Range[int, 1, 10] = 1, private: bool = False):
        campaign = await get_campaign(self.db, interaction.channel)
        display, results = await self._roll_many(campaign, name.strip(), count)
        e = discord.Embed(title=f"{display}", description="\n".join(f"• {r}" for r in results)[:4000],
                          color=COLOR_INFO)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e, ephemeral=private)

    @table.command(name="show", description="Show a table's entries (GM)")
    async def table_show(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        found = await self.db.get_table(campaign.id, name.strip())
        real_name, entries = found if found else (name.strip().lower(), BUILTIN.get(name.strip().lower()))
        if not entries:
            raise UserError(f"No table **{name}**.")
        total = sum(w for w, _ in entries)
        lines = [f"`{w * 100 / total:4.1f}%` {t}" for w, t in entries]
        text = "\n".join(lines)
        if len(text) > 3900:
            text = text[:3900] + "\n…"
        await interaction.response.send_message(
            embed=discord.Embed(title=f"{real_name}" + ("" if found else " (built-in)"), description=text,
                                color=COLOR_INFO), ephemeral=True)

    @table.command(name="list", description="List this campaign's tables and the built-in ones")
    async def table_list(self, interaction: discord.Interaction):
        campaign = await get_campaign(self.db, interaction.channel)
        own = await self.db.list_tables(campaign.id) if campaign else []
        e = discord.Embed(title="Random tables", color=COLOR_INFO)
        e.add_field(name="This campaign", inline=False,
                    value="\n".join(f"**{n}** ({k})" for n, k in own)[:1024] or "*none yet: `/table create`*")
        e.add_field(name="Built-in", inline=False, value=", ".join(f"`{b}`" for b in BUILTIN)[:1024])
        await interaction.response.send_message(embed=e, ephemeral=True)

    @table.command(name="delete", description="Delete a table (GM)")
    async def table_delete(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        if not await self.db.delete_table(campaign.id, name.strip()):
            raise UserError(f"No table **{name}** in this campaign (built-ins can't be deleted).")
        await interaction.response.send_message(f"Table **{name}** deleted.", ephemeral=True)

    table_roll.autocomplete("name")(table_ac)
    table_show.autocomplete("name")(table_ac)
    table_edit.autocomplete("name")(table_ac)
    table_add.autocomplete("name")(own_table_ac)
    table_delete.autocomplete("name")(own_table_ac)

    # ------------------------------------------------------------------ /generate

    @app_commands.command(name="generate", description="Quick inspiration: NPCs, names, taverns, loot, weather…")
    @app_commands.choices(kind=[Choice(name=g.title(), value=g) for g in GENERATORS])
    async def generate(self, interaction: discord.Interaction, kind: Choice[str],
                       count: app_commands.Range[int, 1, 5] = 1, private: bool = False):
        await self.table_roll.callback(self, interaction, kind.value, count, private)

    # ------------------------------------------------------------------ /note

    async def _visible_note(self, interaction, campaign: Campaign, title: str) -> Note:
        note = await self.db.get_note(campaign.id, title.strip())
        if not note or (note.gm_only and not is_gm(interaction.user, campaign)):
            raise UserError(f"No note called **{title}**. Try `/note search`.")
        return note

    def _can_edit(self, interaction, campaign: Campaign, note: Note) -> bool:
        return note.author_id == interaction.user.id or is_gm(interaction.user, campaign)

    async def save_note(self, interaction, campaign: Campaign, title: str, category: str, gm_only: bool,
                        content: str, author_id: int):
        content = content.strip()
        if not content:
            raise UserError("The note is empty.")
        note = await self.db.save_note(campaign.id, title, category, content, gm_only, author_id)
        await interaction.response.send_message(f"Saved **{note.title}**.", embed=note_embed(note),
                                                ephemeral=True)
        await notify(self.bot, interaction.guild_id, [author_id], interaction.channel)

    async def note_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        notes = await self.db.list_notes(campaign.id, include_gm=is_gm(interaction.user, campaign),
                                         query=current or None)
        return [Choice(name=f"{n.title} ({n.category})"[:100], value=n.title) for n in notes][:25]

    @note.command(name="add", description="Write a note. Leave text empty for a big editor")
    @app_commands.describe(title="e.g. Mayor Ulric", category="What kind of note",
                           gm_only="Only GMs can see it", text="Optional: the note text (or use the editor)")
    @app_commands.choices(category=[Choice(name=k, value=k) for k in CATEGORIES])
    async def note_add(self, interaction: discord.Interaction, title: str, category: Optional[Choice[str]] = None,
                       gm_only: bool = False, text: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        title = " ".join(title.split())[:80]
        if not title:
            raise UserError("The note needs a title.")
        if gm_only:
            require_gm(interaction.user, campaign)
        if await self.db.get_note(campaign.id, title):
            raise UserError(f"There's already a note **{title}**. Use `/note edit`.")
        cat = category.value if category else "Lore"
        if text is None:
            await interaction.response.send_modal(
                NoteModal(self, campaign, title, cat, gm_only, interaction.user.id))
            return
        await self.save_note(interaction, campaign, title, cat, gm_only, text, interaction.user.id)

    @note.command(name="edit", description="Edit a note (its author or the GM)")
    @app_commands.choices(category=[Choice(name=k, value=k) for k in CATEGORIES])
    async def note_edit(self, interaction: discord.Interaction, title: str, category: Optional[Choice[str]] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        note = await self._visible_note(interaction, campaign, title)
        if not self._can_edit(interaction, campaign, note):
            raise UserError("Only the note's author or the GM can edit it.")
        await interaction.response.send_modal(NoteModal(
            self, campaign, note.title, category.value if category else note.category, bool(note.gm_only),
            note.author_id, note.content))

    @note.command(name="show", description="Read a note")
    @app_commands.describe(public="Post it for the whole table")
    async def note_show(self, interaction: discord.Interaction, title: str, public: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        note = await self._visible_note(interaction, campaign, title)
        if public and note.gm_only:
            raise UserError("That's a GM-only note. It can't be posted publicly.")
        await interaction.response.send_message(embed=note_embed(note), ephemeral=not public)

    @note.command(name="search", description="Search titles and text of notes")
    async def note_search(self, interaction: discord.Interaction, query: str):
        campaign = await require_campaign(self.db, interaction.channel)
        notes = await self.db.list_notes(campaign.id, include_gm=is_gm(interaction.user, campaign),
                                         query=query.strip())
        if not notes:
            raise UserError(f"Nothing found for **{query}**.")
        lines = []
        for n in notes:
            snippet = n.content.replace("\n", " ")
            i = snippet.lower().find(query.lower())
            if i > 40:
                snippet = "…" + snippet[i - 30:]
            lines.append(f"**{n.title}** · {n.category}{GM_ONLY if n.gm_only else ''}\n"
                         f"-# {snippet[:90]}{'…' if len(snippet) > 90 else ''}")
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    @note.command(name="list", description="List notes, optionally by category")
    @app_commands.choices(category=[Choice(name=k, value=k) for k in CATEGORIES])
    async def note_list(self, interaction: discord.Interaction, category: Optional[Choice[str]] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        notes = await self.db.list_notes(campaign.id, include_gm=is_gm(interaction.user, campaign),
                                         category=category.value if category else None, limit=200)
        if not notes:
            raise UserError("No notes yet. Write one with `/note add`.")
        e = discord.Embed(title="Campaign notes", color=COLOR_INFO)
        by_cat: dict[str, list[str]] = {}
        for n in notes:
            by_cat.setdefault(n.category, []).append(n.title + (" *(GM only)*" if n.gm_only else ""))
        for cat, titles in list(by_cat.items())[:25]:
            e.add_field(name=cat, value=", ".join(titles)[:1024], inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @note.command(name="delete", description="Delete a note (its author or the GM)")
    async def note_delete(self, interaction: discord.Interaction, title: str):
        campaign = await require_campaign(self.db, interaction.channel)
        note = await self._visible_note(interaction, campaign, title)
        if not self._can_edit(interaction, campaign, note):
            raise UserError("Only the note's author or the GM can delete it.")

        async def do():
            await self.db.delete_note(note.id)
        await interaction.response.send_message(f"Delete the note **{note.title}**?",
                                                view=ConfirmDelete(interaction.user.id, do, f"Note **{note.title}**"),
                                                ephemeral=True)

    for _cmd in (note_edit, note_show, note_delete):
        _cmd.autocomplete("title")(note_ac)
    del _cmd


async def setup(bot):
    await bot.add_cog(Lore(bot))
