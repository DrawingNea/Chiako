"""Characters with custom stats (incl. derived formulas), skills, and personal and campaign macros."""
from __future__ import annotations

import io
import json
import re
from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.db import Campaign, Character, IntegrityError, Skill
from core.helpers import (
    COLOR_INFO, BaseView, UserError, get_campaign, load_sheet, require_campaign, require_character, require_gm,
)
from core.sheet import RollEnv, Sheet
from core.i18n import t
from core.sheetcard import CardData, build_card
from dice.engine import DiceError, UnknownReference, example_call, macro_params, validate_name


def validate_character_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= 32:
        raise UserError("Character names must be 1–32 characters.")
    if re.search(r"discord|clyde", name, re.I):
        raise UserError("Discord doesn't allow 'discord' or 'clyde' in names posted via webhooks. Pick another name.")
    return name


def validate_url(url: Optional[str]) -> Optional[str]:
    if url is None:
        return None
    url = url.strip()
    if not re.match(r"^https?://\S+$", url):
        raise UserError("The avatar must be a direct image link starting with `https://`.")
    return url


COLOR_NAMES = {
    "red": 0xE74C3C, "orange": 0xE67E22, "gold": 0xF1C40F, "yellow": 0xF1C40F, "green": 0x2ECC71,
    "teal": 0x1ABC9C, "blue": 0x3498DB, "navy": 0x34495E, "purple": 0x9B59B6, "pink": 0xE91E63,
    "brown": 0x8D6E63, "grey": 0x95A5A6, "gray": 0x95A5A6, "black": 0x23272A, "white": 0xFFFFFE,
}


def parse_color(text: str) -> Optional[int]:
    """'#8e44ad', '8e44ad', 'purple' -> int; 'none'/'default' -> None."""
    text = text.strip().lower()
    if text in ("none", "default", "reset", "-"):
        return None
    if text in COLOR_NAMES:
        return COLOR_NAMES[text]
    m = re.fullmatch(r"#?([0-9a-f]{6}|[0-9a-f]{3})", text)
    if not m:
        raise UserError("Use a hex colour like `#8e44ad`, a name like " + ", ".join(f"`{n}`" for n in list(COLOR_NAMES)[:8])
                        + "…, or `none`.")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h, 16)


def chunk_lines(lines: list[str], limit: int = 1024) -> list[str]:
    chunks, cur = [], ""
    for line in lines:
        line = line[:limit]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    return chunks


PROFILE_FIELDS = {
    "en": ["Age", "Gender", "Pronouns", "Race", "Nationality", "Height", "Weight", "Hair", "Eyes", "Occupation",
           "Birthday", "Hometown", "Alignment", "Faith", "Languages"],
    "de": ["Alter", "Geschlecht", "Pronomen", "Rasse", "Nationalität", "Größe", "Gewicht", "Haare", "Augen", "Beruf",
           "Geburtstag", "Heimat", "Gesinnung", "Glaube", "Sprachen"],
}
MAX_PROFILE_FIELDS = 25
MAX_BIO = 1000


class DescriptionModal(discord.ui.Modal):
    """A short description of the character, shown on the sheet card."""

    def __init__(self, cog: "Characters", character: Character, lang: str):
        super().__init__(title=f"{character.name}"[:45])
        self.cog, self.character, self.lang = cog, character, lang
        self.text = discord.ui.TextInput(
            label=t(lang, "Description (leave empty to remove it)"), style=discord.TextStyle.paragraph,
            default=character.bio or None, max_length=MAX_BIO, required=False,
            placeholder=t(lang, "A wiry half-elf with a crooked smile, always one step ahead of her debts."))
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        bio = (self.text.value or "").strip() or None
        await self.cog.db.update_character(self.character.id, bio=bio)
        await interaction.response.send_message(
            t(self.lang, "Description of **{name}** saved." if bio else "Description of **{name}** removed.",
              name=self.character.name), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        from core.helpers import report_error
        await report_error(interaction, error)


class ConfirmDelete(BaseView):
    def __init__(self, cog: "Characters", owner_id: int, character: Character):
        super().__init__(timeout=60)
        self.cog, self.owner_id, self.character = cog, owner_id, character

    @discord.ui.button(label="Delete forever", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not your character.", ephemeral=True)
            return
        await self.cog.db.delete_character(self.character.id)
        await interaction.response.edit_message(content=f"**{self.character.name}** has been deleted.", view=None)
        await self.cog._refresh(await self.cog.db.get_campaign(self.character.campaign_id))
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Phew. Nothing was deleted.", view=None)
        self.stop()


class Characters(commands.Cog):
    char = app_commands.Group(name="char", description="Your characters", guild_only=True)
    stat = app_commands.Group(name="stat", description="Your active character's stats", guild_only=True)
    skill = app_commands.Group(name="skill", description="Your active character's skills", guild_only=True)
    macro = app_commands.Group(name="macro", description="Roll shortcuts: yours, or the campaign's (GM)", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def _refresh(self, campaign):
        """Keep the live party dashboard in sync with character changes."""
        table = getattr(self.bot, "table", None)
        if table and campaign:
            await table.refresh_dashboard(campaign)

    # ------------------------------------------------------------------ autocomplete

    async def my_characters_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        chars = await self.db.list_characters(campaign.id, interaction.user.id)
        return [Choice(name=c.name, value=c.name) for c in chars if current.lower() in c.name.lower()][:25]

    async def my_stats_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        ch = campaign and await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            return []
        stats = await self.db.get_stats(ch.id)
        return [Choice(name=f"{n} = {f}"[:100], value=n) for n, f in stats.items() if current.lower() in n][:25]

    async def my_skills_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        ch = campaign and await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            return []
        skills = await self.db.get_skills(ch.id)
        return [Choice(name=f"{n} · {s.describe()}"[:100], value=n) for n, s in skills.items() if current.lower() in n][:25]

    async def my_macros_ac(self, interaction: discord.Interaction, current: str):
        if getattr(interaction.namespace, "campaign", False):  # /macro remove campaign:True
            camp = await get_campaign(self.db, interaction.channel)
            macros = await self.db.get_campaign_macros(camp.id) if camp else {}
        else:
            macros = await self.db.get_macros(interaction.guild_id, interaction.user.id)
        return [Choice(name=f"{n} · {e}"[:100], value=n) for n, e in macros.items() if current.lower() in n][:25]

    # ------------------------------------------------------------------ /char

    @char.command(name="create", description="Create a character in this campaign (becomes your active one)")
    @app_commands.describe(name="Character name", avatar_url="Optional image link used as the character's avatar")
    async def char_create(self, interaction: discord.Interaction, name: str, avatar_url: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        name = validate_character_name(name)
        try:
            c = await self.db.create_character(campaign.id, interaction.user.id, name, validate_url(avatar_url))
        except IntegrityError:
            raise UserError(f"You already have a character called **{name}** in this campaign.")
        await self.db.set_active_character(campaign.id, interaction.user.id, c.id)
        await interaction.response.send_message(
            f"**{c.name}** is born and now your active character! 🌸\n"
            "Next: `/stat bulk str=3, dex=2, level=1` and `/skill add stealth 1d20+dex+2`",
            ephemeral=True,
        )
        await self._refresh(campaign)

    @char.command(name="use", description="Switch your active character")
    @app_commands.autocomplete(name=my_characters_ac)
    async def char_use(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        c = await self.db.get_character_by_name(campaign.id, interaction.user.id, name.strip())
        if not c:
            raise UserError(f"You have no character called **{name}** here. See `/char list`.")
        await self.db.set_active_character(campaign.id, interaction.user.id, c.id)
        await interaction.response.send_message(f"You are now playing **{c.name}**.", ephemeral=True)
        await self._refresh(campaign)

    @char.command(name="list", description="List your characters in this campaign")
    async def char_list(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        chars = await self.db.list_characters(campaign.id, interaction.user.id)
        if not chars:
            raise UserError("You have no characters here yet. Use `/char create`.")
        active = await self.db.get_active_character(campaign.id, interaction.user.id)
        names = {c.id: c.name for c in chars}

        def line(c):
            mark = " · *active*" if active and c.id == active.id else ""
            return f"{c.name}{mark}" + (f" · companion of {names.get(c.parent_id, '?')}" if c.is_companion else "")
        mains = [c for c in chars if not c.is_companion]
        lines = []
        for m in mains:
            lines.append(line(m))
            lines += ["\u2003" + line(c) for c in chars if c.parent_id == m.id]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @char.command(name="show", description="Show a character's sheet as a card")
    @app_commands.describe(name="Character (default: your active one)", player="Show another player's character",
                           public="Post it for everyone to see")
    @app_commands.autocomplete(name=my_characters_ac)
    async def char_show(self, interaction: discord.Interaction, name: Optional[str] = None,
                        player: Optional[discord.Member] = None, public: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        owner = player or interaction.user
        if name:
            c = await self.db.get_character_by_name(campaign.id, owner.id, name.strip())
        else:
            c = await self.db.get_active_character(campaign.id, owner.id)
        if not c:
            raise UserError("Character not found.")
        embed = await self.card(campaign, c, owner.display_name)
        await interaction.response.send_message(embed=embed, ephemeral=not public,
                                                allowed_mentions=discord.AllowedMentions.none())

    async def card(self, campaign: Campaign, c: Character, owner_name: str) -> discord.Embed:
        """Collect everything for the character sheet card and build it."""
        from core.progress import resource_max, xp_progress
        lang = campaign.language
        data = CardData(character=c, owner_name=owner_name, sheet=await load_sheet(self.db, c), lang=lang,
                        layout=campaign.sheet_layout)
        table = getattr(self.bot, "table", None)
        if table:
            from core.table import Target
            target = Target(c.name, character=c)
            health = await table.get_health(target)
            data.hp, data.max_hp, data.temp_hp = health.hp, health.max_hp, health.temp_hp
            data.conditions = [x.label() for x in await table.conditions(target)]
        if not c.is_companion:
            data.xp_text = xp_progress(await self.db.get_xp(c.id), campaign.xp_table, lang)
        for r in (await self.db.get_resources(c.id)).values():
            try:
                mx = await resource_max(self.db, c, r)
            except UserError:
                mx = "?"
            data.resources.append((r.name, r.current, mx))
        data.items = await self.db.list_items(campaign.id, c.id)
        data.money = await self.db.get_money(campaign.id, c.id)
        data.companions = [x.name for x in await self.db.list_companions(c.id)]
        if c.is_companion:
            parent = await self.db.get_character(c.parent_id)
            data.parent = parent.name if parent else "?"
        return build_card(data)

    # ------------------------------------------------------------------ profile & description

    async def profile_field_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        lang = campaign.language if campaign else "en"
        options = []
        if campaign:
            c = await self.db.get_active_character(campaign.id, interaction.user.id)
            options += [k for k, _ in (c.profile if c else [])]
        options += [f for f in PROFILE_FIELDS.get(lang, PROFILE_FIELDS["en"]) if f not in options]
        return [Choice(name=o, value=o) for o in options if current.lower() in o.lower()][:25]

    @char.command(name="profile", description="Details about your character: age, hair, eyes, race, height…")
    @app_commands.describe(field="What it is, e.g. Age, Hair, Eyes, Race (or anything you like)",
                           value="The detail, e.g. 24 or 'long, silver'. Leave empty to remove the field")
    @app_commands.autocomplete(field=profile_field_ac)
    async def char_profile(self, interaction: discord.Interaction, field: str, value: Optional[str] = None):
        campaign, c = await require_character(self.db, interaction)
        lang = campaign.language
        field = " ".join(field.split())[:32]
        if not field:
            raise UserError("The field can't be empty.")
        profile = [list(p) for p in c.profile]
        existing = next((p for p in profile if p[0].lower() == field.lower()), None)
        if value is None or not value.strip():
            if not existing:
                raise UserError(t(lang, "**{name}** has no **{field}** in the profile.", name=c.name, field=field))
            profile.remove(existing)
            await self.db.update_character(c.id, profile=profile)
            await interaction.response.send_message(
                t(lang, "Removed **{field}** from **{name}**'s profile.", field=existing[0], name=c.name),
                ephemeral=True)
            return
        value = " ".join(value.split())[:100]
        if existing:
            existing[1] = value
        else:
            if len(profile) >= MAX_PROFILE_FIELDS:
                raise UserError(f"A profile can have at most {MAX_PROFILE_FIELDS} fields.")
            profile.append([field, value])
        await self.db.update_character(c.id, profile=profile)
        await interaction.response.send_message(
            t(lang, "**{name}**'s profile: **{field}** {value}", name=c.name, field=existing[0] if existing else field,
              value=value), ephemeral=True)

    @char.command(name="description", description="A short description of your character (opens an editor)")
    async def char_description(self, interaction: discord.Interaction):
        campaign, c = await require_character(self.db, interaction)
        await interaction.response.send_modal(DescriptionModal(self, c, campaign.language))

    @char.command(name="color", description="The accent colour of your character's sheet card")
    @app_commands.describe(color="A hex colour like #8e44ad, a name like red/blue/gold, or 'none'")
    async def char_color(self, interaction: discord.Interaction, color: str):
        campaign, c = await require_character(self.db, interaction)
        value = parse_color(color)
        await self.db.update_character(c.id, color=value)
        c = await self.db.get_character(c.id)
        await interaction.response.send_message(
            f"**{c.name}**'s card colour is now " + (f"`#{value:06x}`." if value is not None else "the default."),
            embed=await self.card(campaign, c, interaction.user.display_name), ephemeral=True)

    @char.command(name="avatar", description="Set your active character's avatar image")
    @app_commands.describe(url="Direct image link (leave empty to use your Discord avatar)")
    async def char_avatar(self, interaction: discord.Interaction, url: Optional[str] = None):
        _, c = await require_character(self.db, interaction)
        await self.db.update_character(c.id, avatar_url=validate_url(url))
        await interaction.response.send_message(f"Avatar for **{c.name}** updated.", ephemeral=True)

    @char.command(name="rename", description="Rename your active character")
    async def char_rename(self, interaction: discord.Interaction, new_name: str):
        _campaign, c = await require_character(self.db, interaction)
        new_name = validate_character_name(new_name)
        try:
            await self.db.update_character(c.id, name=new_name)
        except IntegrityError:
            raise UserError(f"You already have a character called **{new_name}**.")
        await interaction.response.send_message(f"**{c.name}** is now **{new_name}**.", ephemeral=True)
        await self._refresh(_campaign)

    @char.command(name="delete", description="Delete one of your characters")
    @app_commands.autocomplete(name=my_characters_ac)
    async def char_delete(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        c = await self.db.get_character_by_name(campaign.id, interaction.user.id, name.strip())
        if not c:
            raise UserError(f"You have no character called **{name}** here.")
        comps = await self.db.list_companions(c.id)
        comp_text = f" Their companions ({', '.join(x.name for x in comps)}) go too." if comps else ""
        await interaction.response.send_message(
            f"Really delete **{c.name}** with all stats and skills?{comp_text}",
            view=ConfirmDelete(self, interaction.user.id, c), ephemeral=True,
        )

    @char.command(name="export", description="Download a character (with companions) as a JSON file")
    @app_commands.autocomplete(name=my_characters_ac)
    async def char_export(self, interaction: discord.Interaction, name: Optional[str] = None):
        from core.transfer import export_character
        campaign = await require_campaign(self.db, interaction.channel)
        if name:
            c = await self.db.get_character_by_name(campaign.id, interaction.user.id, name.strip())
        else:
            c = await self.db.get_active_character(campaign.id, interaction.user.id)
        if not c:
            raise UserError("Character not found. Pick one of yours with the `name` option.")
        if c.is_companion:
            c = await self.db.get_character(c.parent_id)
        data = await export_character(self.db, c)
        raw = json.dumps(data, indent=2, ensure_ascii=False).encode()
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", c.name).strip("_") or "character"
        await interaction.response.send_message(
            f"**{c.name}**" + (f" with {len(data['companions'])} companion(s)" if data["companions"] else "")
            + ". Import it anywhere with `/char import`.",
            file=discord.File(io.BytesIO(raw), filename=f"{safe}.json"), ephemeral=True)

    @char.command(name="import", description="Create a character from an exported JSON file")
    @app_commands.describe(file="A .json file from /char export", name="Optional new name")
    async def char_import(self, interaction: discord.Interaction, file: discord.Attachment,
                          name: Optional[str] = None):
        from core.transfer import MAX_BYTES, import_character
        campaign = await require_campaign(self.db, interaction.channel)
        if file.size > MAX_BYTES:
            raise UserError("That file is too big for a character export.")
        try:
            data = json.loads((await file.read()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise UserError("That file isn't valid JSON. Use a file made with `/char export`.")
        main, comps = await import_character(self.db, campaign.id, interaction.user.id, data,
                                             validate_character_name(name) if name else None)
        await self.db.set_active_character(campaign.id, interaction.user.id, main.id)
        extra = f" with companions {', '.join(c.name for c in comps)}" if comps else ""
        await interaction.response.send_message(
            f"Imported **{main.name}**{extra}. It's now your active character.", ephemeral=True)
        await self._refresh(campaign)

    # ------------------------------------------------------------------ /stat

    async def _validate_stat(self, character: Character, name: str, formula: str) -> Optional[str]:
        """Raises on invalid formulas; returns a warning if it references stats that don't exist yet."""
        stats = await self.db.get_stats(character.id)
        stats[name] = formula
        try:
            Sheet(character, stats, {}).resolve(name)
        except UnknownReference as e:
            return str(e)
        return None

    @stat.command(name="set", description="Set a stat: a number (3) or a formula (10 + con * level)")
    @app_commands.describe(name="Stat name, e.g. dex, max_hp", value="Number or dice-free formula using other stats, e.g. 10 + con * level")
    async def stat_set(self, interaction: discord.Interaction, name: str, value: str):
        _campaign, c = await require_character(self.db, interaction)
        name = validate_name(name, "stat name")
        value = value.strip()
        warning = await self._validate_stat(c, name, value)
        await self.db.set_stat(c.id, name, value)
        sheet = await load_sheet(self.db, c)
        shown = value if warning else sheet.resolve(name)
        msg = f"**{c.name}**: `{name}` = **{shown}**"
        if not warning and sheet.is_derived(name):
            msg += f"  (from `{value}`)"
        if warning:
            msg += f"\n{warning} It will work once that stat exists."
        await interaction.response.send_message(msg, ephemeral=True)
        await self._refresh(_campaign)

    @stat.command(name="bulk", description="Set many stats at once: str=3, dex=2, max_hp=10+con")
    @app_commands.describe(entries="Comma or semicolon separated name=value pairs")
    async def stat_bulk(self, interaction: discord.Interaction, entries: str):
        _campaign, c = await require_character(self.db, interaction)
        pairs = []
        for part in re.split(r"[;,\n]", entries):
            if not part.strip():
                continue
            if "=" not in part:
                raise UserError(f"`{part.strip()}` needs the form `name=value`.")
            n, v = part.split("=", 1)
            pairs.append((validate_name(n, "stat name"), v.strip()))
        if not pairs:
            raise UserError("Nothing to set. Example: `str=3, dex=2, level=1`")

        stats = await self.db.get_stats(c.id)
        stats.update(dict(pairs))
        sheet = Sheet(c, stats, {})
        problems = []
        for n, _ in pairs:  # validate everything before saving anything
            try:
                sheet.resolve(n)
            except UnknownReference as e:
                problems.append(f"`{n}`: {e}")
            except DiceError as e:
                raise UserError(f"`{n}`: {e} Nothing was saved.")
        for n, v in pairs:
            await self.db.set_stat(c.id, n, v)

        lines = [f"`{n}` = **{sheet._cache.get(n, v)}**" for n, v in pairs]
        await interaction.response.send_message(
            f"Updated {len(pairs)} stats on **{c.name}**:\n" + "\n".join(lines + problems), ephemeral=True
        )
        await self._refresh(_campaign)

    @stat.command(name="remove", description="Remove a stat")
    @app_commands.autocomplete(name=my_stats_ac)
    async def stat_remove(self, interaction: discord.Interaction, name: str):
        _campaign, c = await require_character(self.db, interaction)
        if not await self.db.delete_stat(c.id, name.strip().lower()):
            raise UserError(f"**{c.name}** has no stat `{name}`.")
        await interaction.response.send_message(f"Removed `{name}` from **{c.name}**.", ephemeral=True)
        await self._refresh(_campaign)

    # ------------------------------------------------------------------ /skill

    async def _validate_formula(self, interaction, character: Optional[Character], name: str, formula: str,
                                as_skill: bool, campaign_id: Optional[int] = None) -> Optional[str]:
        """Test-roll a formula. Raises on syntax errors, returns a warning for unknown references."""
        sheet = None
        if character:
            sheet = await load_sheet(self.db, character)
            if as_skill:
                sheet.skills[name] = Skill(name, "formula", formula)
            campaign_id = campaign_id or character.campaign_id
        macros = await self.db.get_roll_macros(campaign_id, interaction.guild_id, interaction.user.id)
        if not as_skill:
            macros[name] = formula
        try:
            RollEnv(sheet, macros).roll(example_call(name, macro_params(formula)))
        except UnknownReference as e:
            return str(e)
        return None

    @skill.command(name="add", description="Add/replace a skill with a roll formula, e.g. 1d20 + dex + 2")
    @app_commands.describe(name="Skill name, e.g. stealth", formula="Roll formula using dice and stats")
    async def skill_add(self, interaction: discord.Interaction, name: str, formula: str):
        _, c = await require_character(self.db, interaction)
        name = validate_name(name, "skill name")
        formula = formula.strip()
        warning = await self._validate_formula(interaction, c, name, formula, as_skill=True)
        await self.db.set_skill(c.id, Skill(name, "formula", formula))
        call = example_call(name, macro_params(formula))
        msg = f"**{c.name}** learned `{name}`: `{formula}`. Roll it with `/r {call}`" + (
            f" or `/check {name}`." if call == name else ".")
        if warning:
            msg += f"\n{warning}"
        await interaction.response.send_message(msg, ephemeral=True)

    @skill.command(name="add-3d20", description="Add a 3d20 skill (DSA style): three attributes + skill points")
    @app_commands.describe(name="Skill name", attr1="First attribute stat, e.g. mu", attr2="Second attribute stat",
                           attr3="Third attribute stat", points="Skill points (FW)")
    async def skill_add_3d20(self, interaction: discord.Interaction, name: str, attr1: str, attr2: str, attr3: str,
                             points: app_commands.Range[int, 0, 99]):
        _, c = await require_character(self.db, interaction)
        name = validate_name(name, "skill name")
        attrs = [validate_name(a, "attribute") for a in (attr1, attr2, attr3)]
        await self.db.set_skill(c.id, Skill(name, "3d20", attributes=attrs, points=points))
        stats = await self.db.get_stats(c.id)
        missing = [a for a in attrs if a not in stats]
        msg = f"**{c.name}** learned `{name}`: 3d20 vs {'/'.join(attrs)} with {points} points."
        if missing:
            msg += f"\nMissing stats: {', '.join(f'`{m}`' for m in missing)}. Add them with `/stat set`."
        await interaction.response.send_message(msg, ephemeral=True)

    @skill.command(name="remove", description="Remove a skill")
    @app_commands.autocomplete(name=my_skills_ac)
    async def skill_remove(self, interaction: discord.Interaction, name: str):
        _, c = await require_character(self.db, interaction)
        if not await self.db.delete_skill(c.id, name.strip().lower()):
            raise UserError(f"**{c.name}** has no skill `{name}`.")
        await interaction.response.send_message(f"**{c.name}** forgot `{name}`.", ephemeral=True)

    # ------------------------------------------------------------------ /macro

    @macro.command(name="save", description="Save a roll shortcut, e.g. fireball = 8d6 # Fireball")
    @app_commands.describe(name="Shortcut name",
                           expression="What it rolls (stats, skills, macros; $1 = a value you give each roll)",
                           campaign="GM only: save it for everyone in this campaign")
    async def macro_save(self, interaction: discord.Interaction, name: str, expression: str, campaign: bool = False):
        name = validate_name(name, "macro name")
        expression = expression.strip()
        call = example_call(name, macro_params(expression))
        if campaign:
            camp = await require_campaign(self.db, interaction.channel)
            require_gm(interaction.user, camp)
            # Players roll it with their own stats, so missing stats are expected here: only the syntax is checked
            await self._validate_formula(interaction, None, name, expression, as_skill=False, campaign_id=camp.id)
            await self.db.set_campaign_macro(camp.id, name, expression)
            await interaction.response.send_message(
                f"Campaign macro `{name}` saved: `{expression}`. Everyone in **{camp.name}** can roll it with "
                f"`/r {call}` or `[[{call}]]`.")
            return
        camp = await get_campaign(self.db, interaction.channel)
        character = camp and await self.db.get_active_character(camp.id, interaction.user.id)
        warning = await self._validate_formula(interaction, character or None, name, expression, as_skill=False,
                                               campaign_id=camp.id if camp else None)
        await self.db.set_macro(interaction.guild_id, interaction.user.id, name, expression)
        msg = f"Macro `{name}` saved: `{expression}`. Use it with `/r {call}` or `[[{call}]]`."
        if warning:
            msg += f"\n{warning} (fine if it uses stats of a character you'll play later)"
        await interaction.response.send_message(msg, ephemeral=True)

    @macro.command(name="remove", description="Delete a macro")
    @app_commands.describe(campaign="GM only: delete one of this campaign's macros")
    @app_commands.autocomplete(name=my_macros_ac)
    async def macro_remove(self, interaction: discord.Interaction, name: str, campaign: bool = False):
        name = name.strip().lower()
        if campaign:
            camp = await require_campaign(self.db, interaction.channel)
            require_gm(interaction.user, camp)
            if not await self.db.delete_campaign_macro(camp.id, name):
                raise UserError(f"**{camp.name}** has no campaign macro `{name}`.")
            await interaction.response.send_message(f"Campaign macro `{name}` deleted.")
            return
        if not await self.db.delete_macro(interaction.guild_id, interaction.user.id, name):
            raise UserError(f"You have no macro `{name}`.")
        await interaction.response.send_message(f"Macro `{name}` deleted.", ephemeral=True)

    @macro.command(name="list", description="Show your macros and this campaign's macros")
    async def macro_list(self, interaction: discord.Interaction):
        mine = await self.db.get_macros(interaction.guild_id, interaction.user.id)
        camp = await get_campaign(self.db, interaction.channel)
        shared = await self.db.get_campaign_macros(camp.id) if camp else {}
        if not mine and not shared:
            raise UserError("No macros yet. Try `/macro save fireball 8d6 # Fireball`.")
        e = discord.Embed(title="Macros", color=COLOR_INFO)
        if shared:
            lines = [f"`{n}` → `{x}`" + (" *(your own overrides it)*" if n in mine else "") for n, x in shared.items()]
            for i, chunk in enumerate(chunk_lines(lines)):
                e.add_field(name="​" if i else f"Campaign: {camp.name}", value=chunk, inline=False)
        if mine:
            for i, chunk in enumerate(chunk_lines([f"`{n}` → `{x}`" for n, x in mine.items()])):
                e.add_field(name="​" if i else "Yours", value=chunk, inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Characters(bot))
