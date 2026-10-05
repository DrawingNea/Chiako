"""Initiative tracker (/init) and monster templates (/monster)."""
from __future__ import annotations

import random
from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.combat import format_conditions, next_turn
from core.db import Campaign, Character, Encounter, MonsterTemplate
from core.helpers import (
    BaseView, UserError, get_campaign, is_gm, load_env, load_sheet, require_campaign, require_gm,
)
from core.sheet import RollEnv
from core.table import Target

USER_PINGS = discord.AllowedMentions(users=True, roles=False, everyone=False)


class TrackerView(BaseView):
    """Buttons under the initiative tracker. Persistent: they keep working after a bot restart."""

    def __init__(self, cog: "Combat", started: bool):
        super().__init__(timeout=None)
        self.cog = cog
        if not started:
            self.next_turn.label = "Start combat"

    @discord.ui.button(label="Join", emoji="🎲", style=discord.ButtonStyle.success, custom_id="dicebot:init:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.join_fight(interaction, None)

    @discord.ui.button(label="Next turn", style=discord.ButtonStyle.primary, custom_id="dicebot:init:next")
    async def next_turn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.advance(interaction)


def validate_label(raw: str, what: str = "name") -> str:
    name = " ".join(raw.split())
    if not 1 <= len(name) <= 32:
        raise UserError(f"The {what} must be 1–32 characters.")
    return name


class Combat(commands.Cog):
    init = app_commands.Group(name="init", description="Initiative tracker", guild_only=True)
    monster = app_commands.Group(name="monster", description="Monster templates (GM only)", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.table = bot.table

    async def cog_load(self):
        self.bot.add_view(TrackerView(self, started=True))  # routes button presses after restarts

    def tracker_view(self, enc: Encounter) -> TrackerView:
        return TrackerView(self, started=enc.round > 0)

    async def _encounter(self, campaign: Campaign) -> Encounter:
        enc = await self.db.get_active_encounter(campaign.id)
        if not enc:
            raise UserError("There's no fight going on. The GM starts one with `/init start`.")
        return enc

    @staticmethod
    def _roll(env: RollEnv, expression: str) -> tuple[int, str]:
        r = env.roll(expression)
        return r.total, r.breakdown

    def _init_expression(self, campaign: Campaign, env: RollEnv, explicit: Optional[str]) -> str:
        if explicit:
            return explicit
        if env.sheet:
            for name in ("initiative", "init"):
                skill = env.sheet.skills.get(name)
                if skill and skill.kind == "formula":
                    return name
        return campaign.init_formula

    async def _post_tracker(self, interaction: discord.Interaction, campaign: Campaign, enc: Encounter):
        embed = await self.table.tracker_embed(campaign, enc)
        view = self.tracker_view(enc)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, wait=True)
        else:
            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_response()
        await self.db.update_encounter(enc.id, tracker_message_id=msg.id, channel_id=interaction.channel.id)

    async def _unique_name(self, enc: Encounter, base: str, count: int) -> list[str]:
        taken = await self.db.combatant_names(enc.id)
        if count == 1 and base.lower() not in taken:
            return [base]
        names, i = [], 1
        while len(names) < count:
            candidate = f"{base} {i}"
            if candidate.lower() not in taken:
                names.append(candidate)
            i += 1
        return names

    # ------------------------------------------------------------------ joining & adding

    async def join_fight(self, interaction: discord.Interaction, initiative: Optional[str],
                         character: Optional[Character] = None):
        """Join with the active character, or with `character` (e.g. a companion)."""
        campaign = await require_campaign(self.db, interaction.channel)
        enc = await self._encounter(campaign)
        if character:
            env = RollEnv(await load_sheet(self.db, character),
                          await self.db.get_roll_macros(campaign.id, interaction.guild_id, interaction.user.id))
        else:
            env = await load_env(self.db, campaign, interaction.user.id, interaction.guild_id)
        ch = env.character
        if not ch:
            raise UserError("You need an active character to join (`/char create`). The GM adds NPCs with `/init add`.")
        combatants = await self.db.list_combatants(enc.id)
        if any(c.character_id == ch.id for c in combatants):
            raise UserError(f"**{ch.name}** is already in the fight.")
        if ch.name.lower() in {c.name.lower() for c in combatants}:
            raise UserError(f"There's already a combatant called **{ch.name}**.")

        total, detail = self._roll(env, self._init_expression(campaign, env, initiative))
        await self.db.add_combatant(enc.id, ch.name, total, random.random(), character_id=ch.id,
                                    owner_id=interaction.user.id)
        shown = f"**{total}**" if detail.strip() == str(total) else f"{detail} = **{total}**"
        await interaction.response.send_message(f"**{ch.name}** rolls initiative: {shown}")
        await self.table.refresh_all(campaign)

    @init.command(name="start", description="Start a fight in this channel (GM)")
    async def start(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        if await self.db.get_active_encounter(campaign.id):
            raise UserError("A fight is already running. Use `/init show` to find it or `/init end` to stop it.")
        enc = await self.db.create_encounter(campaign.id, interaction.channel.id)
        await self._post_tracker(interaction, campaign, enc)
        await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="fight_start",
                                text="A fight broke out")
        await self.table.refresh_dashboard(campaign)

    @init.command(name="join", description="Join the fight with your active character")
    @app_commands.describe(initiative="Optional: custom roll or fixed number (default: your 'initiative' skill or the campaign formula)")
    async def join(self, interaction: discord.Interaction, initiative: Optional[str] = None):
        await self.join_fight(interaction, initiative)

    @init.command(name="add", description="Add an NPC or monster to the fight (GM)")
    @app_commands.describe(name="Name shown in the tracker", initiative="Roll or number, e.g. 1d20+2 or 15",
                           hp="HP as a number or roll, e.g. 2d8+2", ac="Armor class / defense (GM only)")
    async def add(self, interaction: discord.Interaction, name: str, initiative: str = "1d20",
                  hp: Optional[str] = None, ac: Optional[int] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        enc = await self._encounter(campaign)
        name = validate_label(name)
        if name.lower() in await self.db.combatant_names(enc.id):
            raise UserError(f"There's already a combatant called **{name}**.")
        env = RollEnv(None, {})
        init_total, _ = self._roll(env, initiative)
        hp_total = self._roll(env, hp)[0] if hp else None
        await self.db.add_combatant(enc.id, name, init_total, random.random(), hp=hp_total, max_hp=hp_total, ac=ac)
        hp_text = f", HP {hp_total}" if hp_total is not None else ""
        await interaction.response.send_message(f"Added **{name}** (initiative {init_total}{hp_text}).",
                                                ephemeral=True)
        await self.table.refresh_all(campaign)

    @init.command(name="spawn", description="Add monsters from a template (GM)")
    @app_commands.describe(template="Monster template", count="How many",
                           shared_initiative="Roll initiative once for the whole group")
    async def spawn(self, interaction: discord.Interaction, template: str,
                    count: app_commands.Range[int, 1, 20] = 1, shared_initiative: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        enc = await self._encounter(campaign)
        m = await self.db.get_monster(campaign.id, template.strip())
        if not m:
            raise UserError(f"No monster template **{template}**. Create one with `/monster save`.")
        env = RollEnv(None, {})
        shared = self._roll(env, m.initiative)[0] if shared_initiative else None
        lines = []
        for name in await self._unique_name(enc, m.name, count):
            init_total = shared if shared is not None else self._roll(env, m.initiative)[0]
            hp_total = self._roll(env, m.hp)[0] if m.hp else None
            await self.db.add_combatant(enc.id, name, init_total, random.random(), hp=hp_total, max_hp=hp_total,
                                        ac=m.ac)
            lines.append(f"**{name}**: init {init_total}" + (f", HP {hp_total}" if hp_total is not None else ""))
        await interaction.response.send_message("Spawned:\n" + "\n".join(lines), ephemeral=True)
        await self.table.refresh_all(campaign)

    # ------------------------------------------------------------------ turns

    async def advance(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        enc = await self._encounter(campaign)
        order = await self.db.list_combatants(enc.id)
        if not order:
            raise UserError("Nobody is in the fight yet.")
        gm = is_gm(interaction.user, campaign)
        current = next((c for c in order if c.id == enc.current_id), None) if enc.round > 0 else None
        if enc.round == 0 and not gm:
            raise UserError("Only the GM can start the combat.")
        if enc.round > 0 and not gm and not (current and current.owner_id == interaction.user.id):
            raise UserError("Only the GM or the player whose turn it is can end the turn.")

        lines = []
        if current:  # end of current turn: timed conditions tick down
            key = {"character_id": current.character_id} if current.character_id else {"combatant_id": current.id}
            expired = await self.db.tick_conditions(**key)
            if expired:
                lines.append(f"**{current.name}** is no longer {', '.join(f'**{e}**' for e in expired)}.")

        skip = {c.id for c in order if c.is_monster and c.hp is not None and c.hp <= 0}
        new_id, new_round = next_turn(order, enc.current_id, enc.round, skip)
        await self.db.update_encounter(enc.id, current_id=new_id, round=new_round)
        nxt = next(c for c in order if c.id == new_id)

        if new_round != enc.round:
            lines.append(f"**Round {new_round}**" + (": fight!" if enc.round == 0 else ""))
        nxt_target = Target(nxt.name, character=await self.db.get_character(nxt.character_id) if nxt.character_id
                            else None, combatant=nxt)
        conds = format_conditions(await self.table.conditions(nxt_target))
        ping = f" <@{nxt.owner_id}>" if nxt.owner_id else ""
        lines.append(f"It's **{nxt.name}**'s turn!{ping}" + (f"\n-# {nxt.name}: {conds}" if conds else ""))

        await interaction.response.send_message("\n".join(lines), allowed_mentions=USER_PINGS)
        await self.table.refresh_all(campaign)

    @init.command(name="next", description="End the current turn")
    async def next_cmd(self, interaction: discord.Interaction):
        await self.advance(interaction)

    @init.command(name="move", description="Change someone's initiative, e.g. when delaying (GM)")
    async def move(self, interaction: discord.Interaction, name: str, initiative: int):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        enc = await self._encounter(campaign)
        target = await self.table.resolve_target(campaign, interaction.user.id, name)
        if not target.combatant:
            raise UserError(f"**{target.name}** isn't in the fight.")
        await self.db.update_combatant(target.combatant.id, initiative=initiative)
        await interaction.response.send_message(f"**{target.name}** moves to initiative {initiative}.")
        await self.table.refresh_all(campaign)

    @init.command(name="remove", description="Remove someone from the fight")
    async def remove(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        enc = await self._encounter(campaign)
        target = await self.table.resolve_target(campaign, interaction.user.id, name)
        c = target.combatant
        if not c:
            raise UserError(f"**{target.name}** isn't in the fight.")
        if not is_gm(interaction.user, campaign) and c.owner_id != interaction.user.id:
            raise UserError("You can only remove your own character. The GM can remove anyone.")
        if enc.round > 0 and enc.current_id == c.id:
            order = [x for x in await self.db.list_combatants(enc.id)]
            if len(order) > 1:
                new_id, new_round = next_turn(order, c.id, enc.round)
                await self.db.update_encounter(enc.id, current_id=new_id, round=new_round)
            else:
                await self.db.update_encounter(enc.id, current_id=None)
        await self.db.remove_combatant(c.id)
        await interaction.response.send_message(f"**{c.name}** left the fight.")
        await self.table.refresh_all(campaign)

    @init.command(name="show", description="Re-post the tracker at the bottom of the chat")
    @app_commands.describe(details="GM only: privately show exact monster HP and AC")
    async def show(self, interaction: discord.Interaction, details: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        enc = await self._encounter(campaign)
        if details:
            require_gm(interaction.user, campaign)
            embed = await self.table.tracker_embed(campaign, enc, gm_view=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await self.table._edit(enc.channel_id, enc.tracker_message_id, view=None)  # old copy loses its buttons
        await self._post_tracker(interaction, campaign, enc)

    @init.command(name="end", description="End the fight (GM)")
    async def end(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        enc = await self._encounter(campaign)
        embed = await self.table.tracker_embed(campaign, enc)
        embed.title = f"Fight over after {enc.round} round{'s' if enc.round != 1 else ''}"
        embed.remove_footer()
        await self.table._edit(enc.channel_id, enc.tracker_message_id, embed=embed, view=None)
        await self.db.update_encounter(enc.id, active=0)
        await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="fight_end",
                                text=f"The fight ended after {enc.round} round{'s' if enc.round != 1 else ''}"
                                if enc.round else "The fight ended",
                                value=enc.round)
        await interaction.response.send_message(f"The fight is over after **{enc.round}** "
                                                f"round{'s' if enc.round != 1 else ''}.")
        await self.table.refresh_dashboard(campaign)

    # ------------------------------------------------------------------ autocomplete

    async def combatant_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        enc = campaign and await self.db.get_active_encounter(campaign.id)
        if not enc:
            return []
        return [Choice(name=c.name, value=c.name) for c in await self.db.list_combatants(enc.id)
                if current.lower() in c.name.lower()][:25]

    async def monster_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign or not is_gm(interaction.user, campaign):
            return []
        return [Choice(name=m.name, value=m.name) for m in await self.db.list_monsters(campaign.id)
                if current.lower() in m.name.lower()][:25]

    move.autocomplete("name")(combatant_ac)
    remove.autocomplete("name")(combatant_ac)
    spawn.autocomplete("template")(monster_ac)

    # ------------------------------------------------------------------ /monster

    @monster.command(name="save", description="Create or update a monster template (GM)")
    @app_commands.describe(name="e.g. Goblin", hp="HP roll or number, e.g. 2d6", initiative="e.g. 1d20+2",
                           ac="Armor class / defense", notes="Anything you want to remember (GM only)")
    async def monster_save(self, interaction: discord.Interaction, name: str, hp: Optional[str] = None,
                           initiative: str = "1d20", ac: Optional[int] = None, notes: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        name = validate_label(name, "monster name")
        env = RollEnv(None, {})
        for expr in filter(None, (hp, initiative)):
            self._roll(env, expr)  # validate now rather than at spawn time
        await self.db.save_monster(MonsterTemplate(campaign.id, name, hp, initiative, ac, (notes or "")[:500] or None))
        await interaction.response.send_message(
            f"Template **{name}** saved: HP `{hp or '—'}`, initiative `{initiative}`, AC {ac if ac is not None else '—'}.\n"
            f"Spawn with `/init spawn template:{name} count:3`.", ephemeral=True)

    @monster.command(name="list", description="List monster templates (GM)")
    async def monster_list(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        monsters = await self.db.list_monsters(campaign.id)
        if not monsters:
            raise UserError("No templates yet. Try `/monster save name:Goblin hp:2d6 initiative:1d20+2 ac:15`.")
        lines = [f"**{m.name}** · HP `{m.hp or '—'}` · init `{m.initiative}` · AC {m.ac if m.ac is not None else '—'}"
                 + (f"\n-# {m.notes}" if m.notes else "") for m in monsters]
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    @monster.command(name="remove", description="Delete a monster template (GM)")
    async def monster_remove(self, interaction: discord.Interaction, name: str):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        if not await self.db.delete_monster(campaign.id, name.strip()):
            raise UserError(f"No template **{name}**.")
        await interaction.response.send_message(f"Template **{name}** deleted.", ephemeral=True)

    monster_remove.autocomplete("name")(monster_ac)


async def setup(bot):
    await bot.add_cog(Combat(bot))
