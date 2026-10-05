"""Companions: familiars, pets, summons. Full characters (stats, skills, HP) that belong to a character."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from cogs.characters import validate_character_name, validate_url
from cogs.rolling import ADVANTAGE_CHOICES
from core.db import Campaign, Character, IntegrityError
from core.helpers import UserError, WebhookCache, get_campaign, load_sheet, require_campaign, send_as
from core.achievements import notify
from core.rolls import build_roll, log_roll
from core.sheet import DiceRules, RollEnv


class Companions(commands.Cog):
    companion = app_commands.Group(name="companion", description="Familiars, pets, summons…", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def _refresh(self, campaign):
        table = getattr(self.bot, "table", None)
        if table:
            await table.refresh_dashboard(campaign)

    async def _main(self, interaction: discord.Interaction) -> tuple[Campaign, Character]:
        campaign = await require_campaign(self.db, interaction.channel)
        ch = await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            raise UserError("You need an active character first (`/char create`).")
        if ch.is_companion:
            ch = await self.db.get_character(ch.parent_id)
        return campaign, ch

    async def _companion(self, interaction, name: str) -> tuple[Campaign, Character, Character]:
        campaign, main = await self._main(interaction)
        for c in await self.db.list_companions(main.id):
            if c.name.lower() == name.strip().lower():
                return campaign, main, c
        raise UserError(f"**{main.name}** has no companion called **{name}**.")

    async def companion_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        ch = campaign and await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            return []
        main_id = ch.parent_id if ch.is_companion else ch.id
        return [Choice(name=c.name, value=c.name) for c in await self.db.list_companions(main_id)
                if current.lower() in c.name.lower()][:25]

    @companion.command(name="add", description="Give your character a companion")
    @app_commands.describe(name="e.g. Whiskers", avatar_url="Optional image link")
    async def add(self, interaction: discord.Interaction, name: str, avatar_url: Optional[str] = None):
        campaign, main = await self._main(interaction)
        name = validate_character_name(name)
        if len(await self.db.list_companions(main.id)) >= 10:
            raise UserError("That's a lot of companions. Max 10 per character.")
        try:
            c = await self.db.create_character(campaign.id, interaction.user.id, name, validate_url(avatar_url),
                                               parent_id=main.id)
        except IntegrityError:
            raise UserError(f"You already have a character called **{name}** here.")
        await interaction.response.send_message(
            f"**{c.name}** is now **{main.name}**'s companion!\n"
            f"Roll for it with `/companion roll {c.name} 1d20+2`. To give it stats and skills, switch with "
            f"`/char use {c.name}`, set them with `/stat` and `/skill`, then `/char use {main.name}` to switch back.",
            ephemeral=True)
        await self._refresh(campaign)
        await notify(self.bot, interaction.guild_id, [interaction.user.id], interaction.channel)

    @companion.command(name="list", description="Your character's companions")
    async def list_cmd(self, interaction: discord.Interaction):
        _, main = await self._main(interaction)
        comps = await self.db.list_companions(main.id)
        if not comps:
            raise UserError(f"**{main.name}** has no companions yet. Add one with `/companion add`.")
        table = getattr(self.bot, "table", None)
        lines = []
        for c in comps:
            hp = ""
            if table:
                from core.table import Target
                hp = " · " + await table.describe_health(Target(c.name, character=c), exact=True)
            lines.append(f"**{c.name}**{hp}")
        await interaction.response.send_message(f"**{main.name}**'s companions:\n" + "\n".join(lines),
                                                ephemeral=True)

    @companion.command(name="roll", description="Roll for a companion without switching to it")
    @app_commands.describe(name="Which companion", expression="Dice, its skills, or its @stats",
                           advantage="Advantage / disadvantage")
    @app_commands.choices(advantage=ADVANTAGE_CHOICES)
    async def roll(self, interaction: discord.Interaction, name: str, expression: str,
                   advantage: Optional[Choice[str]] = None):
        campaign, _, comp = await self._companion(interaction, name)
        env = RollEnv(await load_sheet(self.db, comp),
                      await self.db.get_roll_macros(campaign.id, interaction.guild_id, interaction.user.id),
                      DiceRules.of(campaign), lang=campaign.language)
        embed, data = build_roll(env, interaction.user, expression, advantage.value if advantage else None)
        rolling = self.bot.get_cog("Rolling")
        hooks = rolling.hooks if rolling else WebhookCache(self.bot)
        await send_as(interaction, hooks, campaign, comp, embed)
        await log_roll(self.db, data, guild_id=interaction.guild_id, channel_id=interaction.channel_id,
                       campaign=campaign, user_id=interaction.user.id, env=env)
        await notify(self.bot, interaction.guild_id, [interaction.user.id], interaction.channel)

    @companion.command(name="join", description="Add a companion to the current fight")
    @app_commands.describe(initiative="Optional roll or number (default: its 'initiative' skill or the campaign formula)")
    async def join(self, interaction: discord.Interaction, name: str, initiative: Optional[str] = None):
        _, _, comp = await self._companion(interaction, name)
        combat = self.bot.get_cog("Combat")
        if not combat:
            raise UserError("Combat isn't loaded.")
        await combat.join_fight(interaction, initiative, character=comp)

    @companion.command(name="remove", description="Dismiss a companion (deletes it)")
    async def remove(self, interaction: discord.Interaction, name: str):
        campaign, main, comp = await self._companion(interaction, name)
        await self.db.delete_character(comp.id)
        await interaction.response.send_message(f"**{comp.name}** leaves **{main.name}**'s side.", ephemeral=True)
        await self._refresh(campaign)

    for _cmd in (roll, join, remove):
        _cmd.autocomplete("name")(companion_ac)
    del _cmd


async def setup(bot):
    await bot.add_cog(Companions(bot))
