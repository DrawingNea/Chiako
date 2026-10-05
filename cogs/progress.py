"""Resources (/res), rests (/rest) and experience (/xp)."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.achievements import notify
from core.db import Campaign, Character, Resource
from core.helpers import UserError, get_campaign, require_campaign, require_character, require_gm
from core.progress import (
    RESET_LABELS, apply_xp, parse_xp_table, resource_max, rest, xp_progress,
)
from core.sheet import Sheet
from dice.engine import DiceError, UnknownReference, validate_name

RESET_CHOICES = [Choice(name="Short rest", value="short"), Choice(name="Long rest", value="long"),
                 Choice(name="Never (manual)", value="never")]


class Progress(commands.Cog):
    res = app_commands.Group(name="res", description="Resources: spell slots, ammo, ki, luck…", guild_only=True)
    xp = app_commands.Group(name="xp", description="Experience and levels", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def _refresh(self, campaign: Campaign):
        table = getattr(self.bot, "table", None)
        if table:
            await table.refresh_dashboard(campaign)

    async def _resource(self, character: Character, name: str) -> Resource:
        r = (await self.db.get_resources(character.id)).get(name.strip().lower())
        if not r:
            raise UserError(f"**{character.name}** has no resource `{name}`. Add it with `/res add`.")
        return r

    async def resource_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        ch = campaign and await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            return []
        out = []
        for r in (await self.db.get_resources(ch.id)).values():
            if current.lower() in r.name:
                try:
                    mx = await resource_max(self.db, ch, r)
                except UserError:
                    mx = "?"
                out.append(Choice(name=f"{r.name} ({r.current}/{mx})", value=r.name))
        return out[:25]

    # ------------------------------------------------------------------ /res

    @res.command(name="add", description="Add or change a resource, e.g. slots_1 with max 3")
    @app_commands.describe(name="e.g. slots_1, ammo, ki", max="Number or formula, e.g. 3 or level + 1",
                           reset="When it refills", current="Starting value (default: full)")
    @app_commands.choices(reset=RESET_CHOICES)
    async def res_add(self, interaction: discord.Interaction, name: str, max: str,
                      reset: Optional[Choice[str]] = None, current: Optional[int] = None):
        campaign, ch = await require_character(self.db, interaction)
        name = validate_name(name, "resource name")
        sheet = Sheet(ch, await self.db.get_stats(ch.id), {})
        try:
            mx = sheet.resolve_formula(max.strip())
        except UnknownReference as e:
            raise UserError(f"{e} Set the stat first, then add the resource.")
        except DiceError as e:
            raise UserError(f"The max doesn't work: {e}")
        if mx < 0:
            raise UserError("The maximum can't be negative.")
        cur = mx if current is None else min(mx, current)
        if cur < 0:
            raise UserError("The current value can't be negative.")
        kind = reset.value if reset else "long"
        await self.db.set_resource(Resource(ch.id, name, cur, max.strip(), kind))
        await interaction.response.send_message(
            f"**{ch.name}** has `{name}` {cur}/{mx} (refills on {RESET_LABELS[kind]}).", ephemeral=True)
        await self._refresh(campaign)

    @res.command(name="use", description="Spend a resource")
    async def res_use(self, interaction: discord.Interaction, name: str,
                      amount: app_commands.Range[int, 1, 1000] = 1):
        campaign, ch = await require_character(self.db, interaction)
        r = await self._resource(ch, name)
        mx = await resource_max(self.db, ch, r)
        if r.current < amount:
            raise UserError(f"**{ch.name}** only has {r.current}/{mx} `{r.name}` left.")
        await self.db.update_resource_current(ch.id, r.name, r.current - amount)
        empty = " **Empty!**" if r.current - amount == 0 else ""
        await interaction.response.send_message(
            f"**{ch.name}** uses {amount} `{r.name}` → {r.current - amount}/{mx}{empty}")
        await self._refresh(campaign)

    @res.command(name="gain", description="Regain some of a resource (up to its max)")
    async def res_gain(self, interaction: discord.Interaction, name: str,
                       amount: app_commands.Range[int, 1, 1000] = 1):
        campaign, ch = await require_character(self.db, interaction)
        r = await self._resource(ch, name)
        mx = await resource_max(self.db, ch, r)
        new = min(mx, r.current + amount)
        await self.db.update_resource_current(ch.id, r.name, new)
        await interaction.response.send_message(f"**{ch.name}** regains `{r.name}` → {new}/{mx}")
        await self._refresh(campaign)

    @res.command(name="set", description="Set a resource to an exact value")
    async def res_set(self, interaction: discord.Interaction, name: str, value: app_commands.Range[int, 0, 100000]):
        campaign, ch = await require_character(self.db, interaction)
        r = await self._resource(ch, name)
        mx = await resource_max(self.db, ch, r)
        value = min(value, mx)
        await self.db.update_resource_current(ch.id, r.name, value)
        await interaction.response.send_message(f"**{ch.name}**: `{r.name}` = {value}/{mx}", ephemeral=True)
        await self._refresh(campaign)

    @res.command(name="remove", description="Delete a resource")
    async def res_remove(self, interaction: discord.Interaction, name: str):
        campaign, ch = await require_character(self.db, interaction)
        if not await self.db.delete_resource(ch.id, name.strip().lower()):
            raise UserError(f"**{ch.name}** has no resource `{name}`.")
        await interaction.response.send_message(f"Removed `{name}` from **{ch.name}**.", ephemeral=True)
        await self._refresh(campaign)

    @res.command(name="list", description="Show your character's resources")
    async def res_list(self, interaction: discord.Interaction):
        _, ch = await require_character(self.db, interaction)
        resources = await self.db.get_resources(ch.id)
        if not resources:
            raise UserError(f"**{ch.name}** has no resources yet. Try `/res add slots_1 3`.")
        lines = []
        for r in resources.values():
            mx = await resource_max(self.db, ch, r)
            lines.append(f"`{r.name}` **{r.current}/{mx}** · {RESET_LABELS[r.reset]}"
                         + (f" · max `{r.max_formula}`" if not r.max_formula.strip().isdigit() else ""))
        await interaction.response.send_message(f"**{ch.name}**\n" + "\n".join(lines), ephemeral=True)

    for _cmd in (res_use, res_gain, res_set, res_remove):
        _cmd.autocomplete("name")(resource_ac)
    del _cmd

    # ------------------------------------------------------------------ /rest

    async def _party(self, campaign: Campaign) -> list[Character]:
        """Every player's main character (an active companion counts for its owner)."""
        seen, mains = set(), []
        for ch in await self.db.list_active_characters(campaign.id):
            main = await self.db.get_character(ch.parent_id) if ch.is_companion else ch
            if main and main.id not in seen:
                seen.add(main.id)
                mains.append(main)
        return mains

    @app_commands.command(name="rest", description="Short or long rest: refill resources (and HP on a long rest)")
    @app_commands.describe(kind="Short rest refills short-rest resources; long rest refills everything",
                           party="GM only: the whole party rests", restore_hp="Long rest: restore HP to max")
    @app_commands.choices(kind=[Choice(name="Short rest", value="short"), Choice(name="Long rest", value="long")])
    @app_commands.guild_only()
    async def rest_cmd(self, interaction: discord.Interaction, kind: Choice[str], party: bool = False,
                       restore_hp: bool = True):
        campaign = await require_campaign(self.db, interaction.channel)
        if party:
            require_gm(interaction.user, campaign)
            mains = await self._party(campaign)
            if not mains:
                raise UserError("Nobody in this campaign has an active character yet.")
        else:
            _, ch = await require_character(self.db, interaction)
            mains = [await self.db.get_character(ch.parent_id) if ch.is_companion else ch]

        lines = []
        for main in mains:
            for ch in [main] + await self.db.list_companions(main.id):
                changes = await rest(self.db, ch, kind.value, restore_hp)
                lines.append(f"**{ch.name}**: {', '.join(changes) if changes else 'nothing to restore'}")
        await interaction.response.send_message(f"**{kind.name}**\n" + "\n".join(lines))
        await self._refresh(campaign)

    # ------------------------------------------------------------------ /xp

    async def _xp_targets(self, campaign: Campaign, target: Optional[str]) -> list[Character]:
        if not target:
            return await self._party(campaign)
        found = [c for c in await self.db.find_characters(campaign.id, target.strip()) if not c.is_companion]
        if not found:
            raise UserError(f"No character **{target}** in this campaign.")
        if len(found) > 1:
            raise UserError(f"`{target}` matches several characters: {', '.join(c.name for c in found)}.")
        return found

    async def main_character_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        return [Choice(name=c.name, value=c.name) for c in await self.db.list_characters(campaign.id)
                if not c.is_companion and current.lower() in c.name.lower()][:25]

    @xp.command(name="award", description="Give XP to the party or one character (GM)")
    @app_commands.describe(amount="XP to give", target="One character (default: the whole party)",
                           split="Divide the amount between everyone instead of giving each the full amount",
                           reason="What it's for")
    async def xp_award(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 10_000_000],
                       target: Optional[str] = None, split: bool = False, reason: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        chars = await self._xp_targets(campaign, target)
        if not chars:
            raise UserError("Nobody in this campaign has an active character yet.")
        each = amount // len(chars) if split else amount
        lines, level_ups = [], []
        for ch in chars:
            new_level = await apply_xp(self.db, ch, await self.db.get_xp(ch.id) + each, campaign.xp_table)
            lines.append(f"**{ch.name}** +{each:,} → {xp_progress(await self.db.get_xp(ch.id), campaign.xp_table)}")
            if new_level:
                level_ups.append(f"**{ch.name}** reached **level {new_level}**!")
                await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="levelup",
                                        text=f"{ch.name} reached level {new_level}", user_id=ch.owner_id,
                                        value=new_level)
        head = f"**{each:,} XP**" + (" each" if len(chars) > 1 else "") + (f" for *{reason}*" if reason else "")
        if level_ups:
            level_ups[-1] += " ✨"  # one sparkle for the whole message
        await interaction.response.send_message("\n".join([head] + lines + level_ups))
        await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="xp",
                                text=f"{each:,} XP" + (" each" if len(chars) > 1 else f" for {chars[0].name}")
                                + (f" for {reason}" if reason else ""), value=each * len(chars))
        await self._refresh(campaign)
        await notify(self.bot, interaction.guild_id, [c.owner_id for c in chars], interaction.channel)

    @xp.command(name="set", description="Set a character's XP exactly (GM)")
    async def xp_set(self, interaction: discord.Interaction, target: str,
                     amount: app_commands.Range[int, 0, 100_000_000]):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        ch = (await self._xp_targets(campaign, target))[0]
        new_level = await apply_xp(self.db, ch, amount, campaign.xp_table)
        text = f"**{ch.name}**: {xp_progress(amount, campaign.xp_table)}"
        if new_level:
            text += f"\nLevel is now **{new_level}**."
            await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="levelup",
                                    text=f"{ch.name} reached level {new_level}", user_id=ch.owner_id,
                                    value=new_level)
        await interaction.response.send_message(text, ephemeral=True)
        await self._refresh(campaign)
        await notify(self.bot, interaction.guild_id, [ch.owner_id], interaction.channel)

    @xp.command(name="show", description="Show XP and level progress")
    async def xp_show(self, interaction: discord.Interaction, target: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        if target:
            chars = await self._xp_targets(campaign, target)
        else:
            _, ch = await require_character(self.db, interaction)
            chars = [await self.db.get_character(ch.parent_id) if ch.is_companion else ch]
        lines = [f"**{c.name}**: {xp_progress(await self.db.get_xp(c.id), campaign.xp_table)}" for c in chars]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @xp.command(name="table", description="Set the XP needed per level (GM): dnd5e, pathfinder, none or numbers")
    @app_commands.describe(thresholds="Preset or XP for level 1, 2, 3…, e.g. 0, 1000, 3000, 6000")
    async def xp_table(self, interaction: discord.Interaction, thresholds: str):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        table = parse_xp_table(thresholds)
        await self.db.update_campaign(campaign.id, xp_table=table)
        if not table:
            await interaction.response.send_message("XP is tracked without levels now.")
            return
        preview = ", ".join(f"L{i + 1}: {t:,}" for i, t in enumerate(table[:8])) + (" …" if len(table) > 8 else "")
        await interaction.response.send_message(
            f"Level table set ({len(table)} levels): {preview}\n"
            "-# Crossing a threshold updates the character's `level` stat automatically "
            "(unless it's a formula).")

    xp_set.autocomplete("target")(main_character_ac)
    xp_show.autocomplete("target")(main_character_ac)
    xp_award.autocomplete("target")(main_character_ac)


async def setup(bot):
    await bot.add_cog(Progress(bot))
