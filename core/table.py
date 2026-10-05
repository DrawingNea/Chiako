"""
Shared state of the gaming table: who can be targeted, HP of characters and monsters,
and the two live messages (initiative tracker and party dashboard) that update themselves.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import discord

from dice.engine import DiceError

from .combat import format_conditions, health_status, hp_bar
from .db import Campaign, Character, Combatant, Condition, Database, Encounter
from .helpers import COLOR_INFO, UserError, load_sheet

log = logging.getLogger("dicebot")


@dataclass
class Target:
    """Something with HP and conditions: a player character or a monster combatant."""
    name: str
    character: Optional[Character] = None
    combatant: Optional[Combatant] = None

    @property
    def owner_id(self) -> Optional[int]:
        if self.character:
            return self.character.owner_id
        return self.combatant.owner_id if self.combatant else None

    @property
    def is_monster(self) -> bool:
        return self.character is None

    @property
    def cond_key(self) -> dict:
        return {"character_id": self.character.id} if self.character else {"combatant_id": self.combatant.id}


@dataclass
class Health:
    hp: Optional[int]
    max_hp: Optional[int]
    temp_hp: int


class TableService:
    def __init__(self, bot):
        self.bot = bot
        self.db: Database = bot.db

    # ------------------------------------------------------------------ targets

    async def resolve_target(self, campaign: Campaign, user_id: int, text: Optional[str]) -> Target:
        if not text:
            ch = await self.db.get_active_character(campaign.id, user_id)
            if not ch:
                raise UserError("Name a target, or create an active character with `/char create`.")
            return Target(ch.name, character=ch)

        text = text.strip()
        enc = await self.db.get_active_encounter(campaign.id)
        if enc:
            found = await self.db.find_combatants(enc.id, text)
            if len(found) == 1:
                c = found[0]
                if c.character_id:
                    return Target(c.name, character=await self.db.get_character(c.character_id), combatant=c)
                return Target(c.name, combatant=c)
            if len(found) > 1:
                raise UserError(f"`{text}` matches several combatants: {', '.join(c.name for c in found[:10])}.")

        chars = await self.db.find_characters(campaign.id, text)
        if len(chars) == 1:
            return Target(chars[0].name, character=chars[0])
        if len(chars) > 1:
            raise UserError(f"`{text}` matches several characters: {', '.join(c.name for c in chars[:10])}.")
        raise UserError(f"I can't find **{text}** in this campaign or the current fight.")

    async def target_choices(self, campaign: Optional[Campaign], current: str) -> list[str]:
        if not campaign:
            return []
        names: list[str] = []
        enc = await self.db.get_active_encounter(campaign.id)
        if enc:
            names += [c.name for c in await self.db.list_combatants(enc.id)]
        names += [c.name for c in await self.db.list_characters(campaign.id) if c.name not in names]
        return [n for n in names if current.lower() in n.lower()][:25]

    # ------------------------------------------------------------------ health

    async def character_max_hp(self, character: Character) -> Optional[int]:
        sheet = await load_sheet(self.db, character)
        if "max_hp" not in sheet.stats:
            return None
        try:
            return sheet.resolve("max_hp")
        except DiceError:
            return None

    async def get_health(self, target: Target) -> Health:
        if target.character:
            hp, temp = await self.db.get_character_state(target.character.id)
            max_hp = await self.character_max_hp(target.character)
            if hp is None:
                hp = max_hp
            return Health(hp, max_hp, temp)
        c = await self.db.get_combatant(target.combatant.id)
        return Health(c.hp, c.max_hp, c.temp_hp)

    async def set_health(self, target: Target, hp: Optional[int], temp_hp: int, max_hp: Optional[int] = None):
        if target.character:
            await self.db.set_character_state(target.character.id, hp, temp_hp)
        else:
            fields = {"hp": hp, "temp_hp": temp_hp}
            if max_hp is not None:
                fields["max_hp"] = max_hp
            await self.db.update_combatant(target.combatant.id, **fields)

    async def conditions(self, target: Target) -> list[Condition]:
        return await self.db.get_conditions(**target.cond_key)

    async def describe_health(self, target: Target, *, exact: bool) -> str:
        h = await self.get_health(target)
        if target.is_monster and not exact:
            return health_status(h.hp, h.max_hp)
        text = hp_bar(h.hp, h.max_hp)
        if h.temp_hp:
            text += f" +{h.temp_hp} temp"
        return text

    # ------------------------------------------------------------------ tracker

    async def tracker_embed(self, campaign: Campaign, enc: Encounter, *, gm_view: bool = False) -> discord.Embed:
        combatants = await self.db.list_combatants(enc.id)
        if enc.round == 0:
            title, color = "Roll for initiative!", discord.Color.orange()
        else:
            title, color = f"Round {enc.round}", discord.Color.red()

        lines = []
        for c in combatants:
            t = Target(c.name, character=await self.db.get_character(c.character_id) if c.character_id else None,
                       combatant=c)
            health = await self.describe_health(t, exact=gm_view or not c.is_monster)
            conds = format_conditions(await self.conditions(t))
            marker = "**→**" if c.id == enc.current_id and enc.round > 0 else "\u2003"  # whose turn it is
            extra = f" · AC {c.ac}" if gm_view and c.ac is not None else ""
            line = f"{marker} `{c.initiative:>3}` **{c.name}** · {health}{extra}"
            if conds:
                line += f"\n\u2003\u2003⤷ {conds}"
            lines.append(line)

        desc = "\n".join(lines) if lines else "*Nobody yet. Players press **Join**, the GM uses `/init add` or `/init spawn`.*"
        if len(desc) > 4000:
            desc = desc[:3990] + "\n…"
        e = discord.Embed(title=title, description=desc, color=color)
        if enc.round == 0:
            e.set_footer(text="Join rolls initiative for your active character · GM presses Start when ready")
        else:
            e.set_footer(text="Next turn: the GM or whoever's turn it is")
        if gm_view:
            e.title += " (GM view)"
        return e

    # ------------------------------------------------------------------ dashboard

    async def dashboard_embed(self, campaign: Campaign) -> discord.Embed:
        e = discord.Embed(title=f"Party · {campaign.name}", color=COLOR_INFO)
        from .progress import resources_line
        active = await self.db.list_active_characters(campaign.id)
        # an active companion stands in for its owner's main character
        mains, seen = [], set()
        for ch in active:
            main = await self.db.get_character(ch.parent_id) if ch.is_companion else ch
            if main and main.id not in seen:
                seen.add(main.id)
                mains.append(main)
        if not mains:
            e.description = "*No active characters yet.*"
        shown = 0
        for main in mains:
            for ch in [main] + await self.db.list_companions(main.id):
                if shown >= 25:
                    break
                t = Target(ch.name, character=ch)
                value = await self.describe_health(t, exact=True)
                conds = format_conditions(await self.conditions(t))
                if conds:
                    value += f"\n⤷ {conds}"
                res = await resources_line(self.db, ch)
                if res:
                    value += f"\n{res}"
                owner = f"{main.name}" if ch.is_companion else f"<@{ch.owner_id}>"
                e.add_field(name=ch.name, value=f"{value}\n-# {owner}"[:1024], inline=True)
                shown += 1

        enc = await self.db.get_active_encounter(campaign.id)
        if enc and enc.round > 0 and enc.current_id:
            cur = await self.db.get_combatant(enc.current_id)
            e.set_footer(text=f"In combat · round {enc.round} · {cur.name if cur else '?'}'s turn")
        elif enc:
            e.set_footer(text="Rolling initiative…")
        else:
            e.set_footer(text="Out of combat")
        return e

    # ------------------------------------------------------------------ live messages

    async def _edit(self, channel_id: Optional[int], message_id: Optional[int], **kwargs) -> bool:
        if not channel_id or not message_id:
            return False
        channel = self.bot.get_channel(channel_id)
        try:
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
            await channel.get_partial_message(message_id).edit(**kwargs)
            return True
        except discord.NotFound:
            return False
        except discord.HTTPException as e:
            log.warning("Couldn't update live message: %s", e)
            return True  # keep the reference; maybe a temporary problem

    async def refresh_tracker(self, campaign: Campaign, view_factory=None):
        enc = await self.db.get_active_encounter(campaign.id)
        if not enc or not enc.tracker_message_id:
            return
        kwargs = {"embed": await self.tracker_embed(campaign, enc)}
        if view_factory:
            kwargs["view"] = view_factory(enc)
        if not await self._edit(enc.channel_id, enc.tracker_message_id, **kwargs):
            await self.db.update_encounter(enc.id, tracker_message_id=None)

    async def refresh_dashboard(self, campaign: Campaign):
        campaign = await self.db.get_campaign(campaign.id)  # ids may have changed
        if not campaign.dashboard_message_id:
            return
        ok = await self._edit(campaign.dashboard_channel_id, campaign.dashboard_message_id,
                              embed=await self.dashboard_embed(campaign))
        if not ok:
            await self.db.update_campaign(campaign.id, dashboard_message_id=None)

    async def refresh_all(self, campaign: Campaign):
        cog = self.bot.get_cog("Combat")
        await self.refresh_tracker(campaign, cog.tracker_view if cog else None)
        await self.refresh_dashboard(campaign)
