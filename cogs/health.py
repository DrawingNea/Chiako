"""HP (/hp), conditions (/condition) and the live party dashboard (/dashboard)."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.achievements import notify
from core.combat import apply_damage, apply_heal, apply_temp
from core.helpers import UserError, get_campaign, is_gm, load_env, require_campaign
from core.table import Target

COMMON_CONDITIONS = [
    "Blessed", "Blinded", "Charmed", "Concentrating", "Deafened", "Exhausted", "Frightened", "Grappled",
    "Hidden", "Incapacitated", "Invisible", "Paralyzed", "Poisoned", "Prone", "Restrained", "Stunned",
    "Unconscious", "Burning", "Bleeding", "Inspired",
]


class Health(commands.Cog):
    hp = app_commands.Group(name="hp", description="Hit points of characters and monsters", guild_only=True)
    condition = app_commands.Group(name="condition", description="Conditions like Stunned or Poisoned",
                                   guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.table = bot.table

    # ------------------------------------------------------------------ helpers

    async def _setup(self, interaction: discord.Interaction, target: Optional[str]):
        campaign = await require_campaign(self.db, interaction.channel)
        return campaign, await self.table.resolve_target(campaign, interaction.user.id, target)

    async def _amount(self, interaction, campaign, text: str) -> tuple[int, str]:
        env = await load_env(self.db, campaign, interaction.user.id, interaction.guild_id)
        r = env.roll(text)
        return r.total, f" ({r.breakdown})" if r.terms else ""

    async def _need_hp(self, target: Target):
        h = await self.table.get_health(target)
        if h.hp is None:
            hint = ("Give the character a `max_hp` stat (`/stat set max_hp 20`) or use `/hp set`."
                    if target.character else "The GM can set it with `/hp set`.")
            raise UserError(f"**{target.name}** has no HP yet. {hint}")
        return h

    async def _is_their_turn(self, campaign, target: Target) -> bool:
        """Conditions applied during the target's own turn start counting down at its *next* turn."""
        enc = await self.db.get_active_encounter(campaign.id)
        if not enc or enc.round == 0 or not enc.current_id:
            return False
        cur = await self.db.get_combatant(enc.current_id)
        if not cur:
            return False
        if target.character:
            return cur.character_id == target.character.id
        return cur.id == target.combatant.id

    def _can_edit_exactly(self, interaction, campaign, target: Target) -> bool:
        return is_gm(interaction.user, campaign) or (target.character and target.owner_id == interaction.user.id)

    async def target_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        return [Choice(name=n, value=n) for n in await self.table.target_choices(campaign, current)]

    # ------------------------------------------------------------------ /hp

    @hp.command(name="damage", description="Deal damage (temp HP absorbs it first)")
    @app_commands.describe(amount="Number or roll, e.g. 7 or 2d6+3", target="Who (default: your character)")
    async def damage(self, interaction: discord.Interaction, amount: str, target: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        h = await self._need_hp(t)
        total, detail = await self._amount(interaction, campaign, amount)
        hp, temp, absorbed = apply_damage(h.hp, h.temp_hp, total)
        await self.table.set_health(t, hp, temp)
        status = await self.table.describe_health(t, exact=not t.is_monster)
        msg = f"**{t.name}** takes **{total}** damage{detail}"
        if absorbed:
            msg += f", {absorbed} absorbed by temp HP"
        msg += f" → {status}"
        knocked_out = hp == 0 and h.hp > 0
        if knocked_out:
            msg += f"\n**{t.name}** {'is defeated!' if t.is_monster else 'drops to 0 HP!'}"
        await interaction.response.send_message(msg)
        await self.table.refresh_all(campaign)
        if knocked_out:
            if t.is_monster:
                await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="defeat",
                                        text=f"{t.name} was defeated", user_id=interaction.user.id)
            else:
                await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="down",
                                        text=f"{t.name} dropped to 0 HP", user_id=t.owner_id)
            await notify(self.bot, interaction.guild_id, [interaction.user.id], interaction.channel)

    @hp.command(name="heal", description="Heal (can't go above max HP)")
    @app_commands.describe(amount="Number or roll, e.g. 2d4+2", target="Who (default: your character)")
    async def heal(self, interaction: discord.Interaction, amount: str, target: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        h = await self._need_hp(t)
        total, detail = await self._amount(interaction, campaign, amount)
        hp = apply_heal(h.hp, h.max_hp, total)
        await self.table.set_health(t, hp, h.temp_hp)
        status = await self.table.describe_health(t, exact=not t.is_monster)
        msg = f"**{t.name}** heals **{total}**{detail} → {status}"
        revived = h.hp == 0 and hp > 0
        if revived:
            msg += f"\n**{t.name}** is back on their feet!"
        await interaction.response.send_message(msg)
        await self.table.refresh_all(campaign)
        if revived and not t.is_monster:
            await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="revive",
                                    text=f"{t.name} got back up", user_id=t.owner_id)
            await notify(self.bot, interaction.guild_id, [t.owner_id], interaction.channel)

    @hp.command(name="temp", description="Give temporary HP (doesn't stack, the higher value wins)")
    async def temp(self, interaction: discord.Interaction, amount: str, target: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        h = await self._need_hp(t)
        total, detail = await self._amount(interaction, campaign, amount)
        await self.table.set_health(t, h.hp, apply_temp(h.temp_hp, total))
        status = await self.table.describe_health(t, exact=not t.is_monster)
        await interaction.response.send_message(f"**{t.name}** gains **{total}** temp HP{detail} → {status}")
        await self.table.refresh_all(campaign)

    @hp.command(name="set", description="Set HP directly (your own character, or anything for the GM)")
    @app_commands.describe(hp="Current HP", target="Who (default: your character)",
                           max_hp="Monsters only: new maximum (characters use the max_hp stat)")
    async def set_hp(self, interaction: discord.Interaction, hp: app_commands.Range[int, 0, 100000],
                     target: Optional[str] = None, max_hp: Optional[app_commands.Range[int, 1, 100000]] = None):
        campaign, t = await self._setup(interaction, target)
        if not self._can_edit_exactly(interaction, campaign, t):
            raise UserError("You can only set your own character's HP. Use `/hp damage` or `/hp heal` instead.")
        h = await self.table.get_health(t)
        if max_hp is not None and t.character:
            raise UserError("For characters, max HP is the `max_hp` stat: `/stat set max_hp 30`.")
        new_max = max_hp if max_hp is not None else h.max_hp
        if new_max is not None:
            hp = min(hp, new_max)
        await self.table.set_health(t, hp, h.temp_hp, max_hp)
        text = f"**{t.name}**: {await self.table.describe_health(t, exact=True)}"
        await interaction.response.send_message(text, ephemeral=t.is_monster)
        await self.table.refresh_all(campaign)

    @hp.command(name="show", description="Show HP (exact numbers for monsters only for the GM)")
    async def show(self, interaction: discord.Interaction, target: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        exact = not t.is_monster or is_gm(interaction.user, campaign)
        text = f"**{t.name}**: {await self.table.describe_health(t, exact=exact)}"
        conds = await self.table.conditions(t)
        if conds:
            text += "\n" + "\n".join(f"{c.label()}" + (f": {c.note}" if c.note else "") for c in conds)
        await interaction.response.send_message(text, ephemeral=True)

    for _cmd in (damage, heal, temp, set_hp, show):
        _cmd.autocomplete("target")(target_ac)
    del _cmd  # don't leave a stray command attribute on the class

    # ------------------------------------------------------------------ /condition

    @condition.command(name="add", description="Add a condition, optionally for a number of rounds")
    @app_commands.describe(name="e.g. Stunned (or anything you like)", target="Who (default: your character)",
                           rounds="Counts down at the end of the target's turns. Empty = until removed",
                           note="Optional note, e.g. 'save DC 13 ends it'")
    async def condition_add(self, interaction: discord.Interaction, name: str, target: Optional[str] = None,
                            rounds: Optional[app_commands.Range[int, 1, 100]] = None, note: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        name = " ".join(name.split())[:32]
        if not name:
            raise UserError("The condition needs a name.")
        name = name[0].upper() + name[1:]
        await self.db.add_condition(**t.cond_key, name=name, rounds=rounds, note=(note or "")[:200] or None,
                                    fresh=await self._is_their_turn(campaign, t))
        duration = f" for **{rounds}** round{'s' if rounds != 1 else ''}" if rounds else ""
        await interaction.response.send_message(f"**{t.name}** is now **{name}**{duration}."
                                                + (f"\n-# {note}" if note else ""))
        await self.table.refresh_all(campaign)

    @condition.command(name="remove", description="Remove a condition")
    async def condition_remove(self, interaction: discord.Interaction, name: str, target: Optional[str] = None):
        campaign, t = await self._setup(interaction, target)
        if not await self.db.remove_condition(**t.cond_key, name=name.strip()):
            raise UserError(f"**{t.name}** isn't **{name}**.")
        await interaction.response.send_message(f"**{t.name}** is no longer **{name.strip()}**.")
        await self.table.refresh_all(campaign)

    @condition_add.autocomplete("name")
    async def condition_name_ac(self, interaction: discord.Interaction, current: str):
        return [Choice(name=c, value=c) for c in COMMON_CONDITIONS if current.lower() in c.lower()][:25]

    @condition_remove.autocomplete("name")
    async def active_condition_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        try:
            t = await self.table.resolve_target(campaign, interaction.user.id, interaction.namespace.target)
        except UserError:
            return []
        return [Choice(name=c.label(), value=c.name) for c in await self.table.conditions(t)
                if current.lower() in c.name.lower()][:25]

    condition_add.autocomplete("target")(target_ac)
    condition_remove.autocomplete("target")(target_ac)

    # ------------------------------------------------------------------ /dashboard

    @app_commands.command(name="dashboard", description="Post a live party overview that updates itself")
    @app_commands.guild_only()
    async def dashboard(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        old = (campaign.dashboard_channel_id, campaign.dashboard_message_id)
        await interaction.response.send_message(embed=await self.table.dashboard_embed(campaign))
        msg = await interaction.original_response()
        await self.db.update_campaign(campaign.id, dashboard_channel_id=interaction.channel.id,
                                      dashboard_message_id=msg.id)
        if old[1]:
            await self.table._edit(*old, content="-# This dashboard moved further down.", embed=None)
        await interaction.followup.send("Tip: pin this message. It keeps itself up to date (HP, conditions, resources, companions).",
                                        ephemeral=True)


async def setup(bot):
    await bot.add_cog(Health(bot))
