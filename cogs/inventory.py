"""Inventory and money: /item, /money and /inventory, for characters and the campaign's party stash."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.db import Campaign, Character
from core.helpers import COLOR_INFO, UserError, get_campaign, is_gm, require_campaign
from core.i18n import t
from core.inventory import fmt_item, fmt_money, item_lines

STASH = "__stash__"           # autocomplete value for the party stash
DEFAULT_CURRENCY = "gold"


def clean_name(text: str, what: str, max_len: int) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise UserError(f"The {what} can't be empty.")
    if len(text) > max_len:
        raise UserError(f"The {what} can be at most {max_len} characters.")
    return text


class Inventory(commands.Cog):
    item = app_commands.Group(name="item", description="Items of your character or the party stash", guild_only=True)
    money = app_commands.Group(name="money", description="Money of your character or the party stash",
                               guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------------ helpers

    async def _active(self, interaction: discord.Interaction, campaign: Campaign) -> Character:
        ch = await self.db.get_active_character(campaign.id, interaction.user.id)
        if not ch:
            raise UserError("You don't have an active character in this campaign. Use `/char create` or `/char use`.")
        return ch

    async def _find(self, campaign: Campaign, name: str) -> Character:
        found = await self.db.find_characters(campaign.id, name.strip())
        exact = [c for c in found if c.name.lower() == name.strip().lower()]
        found = exact or found
        if not found:
            raise UserError(f"There's no character called **{name}** in this campaign.")
        if len(found) > 1:
            raise UserError(f"`{name}` matches {', '.join(c.name for c in found[:5])}. Type more of the name.")
        return found[0]

    async def _owner(self, interaction: discord.Interaction, campaign: Campaign, character: Optional[str],
                     stash: bool) -> Optional[Character]:
        """Whose inventory a command changes: None = the party stash. Other characters need the owner or GM."""
        if stash or character == STASH:
            return None
        if character:
            ch = await self._find(campaign, character)
            if ch.owner_id != interaction.user.id and not is_gm(interaction.user, campaign):
                raise UserError("Only the GM can change other players' characters.")
            return ch
        return await self._active(interaction, campaign)

    async def _target(self, campaign: Campaign, to: str) -> Optional[Character]:
        return None if to == STASH else await self._find(campaign, to)

    @staticmethod
    def _who(lang: str, owner: Optional[Character], start: bool = False) -> str:
        """The character's name, or 'the party stash' (capitalised when it starts a sentence)."""
        if owner:
            return f"**{owner.name}**"
        text = t(lang, "the party stash")
        return text[:1].upper() + text[1:] if start else text

    async def _currency(self, campaign: Campaign, owner: Optional[Character], currency: Optional[str]) -> str:
        """The given currency, or the one this purse (or the campaign) already uses."""
        if currency:
            return clean_name(currency, "currency", 32)
        purse = await self.db.get_money(campaign.id, owner.id if owner else None)
        if len(purse) == 1:
            return next(iter(purse))
        used = await self.db.campaign_currencies(campaign.id)
        return used[0] if used else DEFAULT_CURRENCY

    async def _send(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(text, allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------------ autocomplete

    async def owner_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        lang = campaign.language
        options = [Choice(name=t(lang, "Party stash"), value=STASH)]
        options += [Choice(name=c.name, value=c.name) for c in await self.db.list_characters(campaign.id)]
        cur = current.lower()
        return [o for o in options if cur in o.name.lower()][:25]

    async def _item_choices(self, campaign: Campaign, owner_id: Optional[int], current: str):
        items = await self.db.list_items(campaign.id, owner_id)
        return [Choice(name=fmt_item(i.qty, i.name)[:100], value=i.name)
                for i in items if current.lower() in i.name.lower()][:25]

    async def item_ac(self, interaction: discord.Interaction, current: str):
        """Items of whoever the command is about: the stash, the chosen character, or your active one."""
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        ns = interaction.namespace
        if getattr(ns, "stash", False) or getattr(ns, "character", None) == STASH:
            owner_id = None
        elif getattr(ns, "character", None):
            found = await self.db.find_characters(campaign.id, ns.character)
            owner_id = found[0].id if found else -1
        else:
            ch = await self.db.get_active_character(campaign.id, interaction.user.id)
            owner_id = ch.id if ch else -1
        return await self._item_choices(campaign, owner_id, current)

    async def stash_item_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        return await self._item_choices(campaign, None, current) if campaign else []

    async def currency_ac(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        used = await self.db.campaign_currencies(campaign.id) if campaign else []
        options = used + [c for c in (DEFAULT_CURRENCY, "silver", "copper") if c not in used]
        return [Choice(name=c, value=c) for c in options if current.lower() in c.lower()][:25]

    # ------------------------------------------------------------------ /item

    @item.command(name="add", description="Add an item to your character, or to the party stash")
    @app_commands.describe(name="What it is, e.g. Rope", amount="How many (default 1)", note="Optional note",
                           character="GM: give it to another character", stash="Put it into the party stash")
    @app_commands.autocomplete(character=owner_ac)
    async def item_add(self, interaction: discord.Interaction, name: str,
                       amount: app_commands.Range[int, 1, 1_000_000] = 1, note: Optional[str] = None,
                       character: Optional[str] = None, stash: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        owner = await self._owner(interaction, campaign, character, stash)
        name = clean_name(name, "item name", 100)
        note = clean_name(note, "note", 300) if note else None
        item = await self.db.add_item(campaign.id, owner.id if owner else None, name, amount, note)
        await self._send(interaction, t(lang, "{who} gets **{item}** (now {n}).", who=self._who(lang, owner, True),
                                        item=fmt_item(amount, item.name), n=item.qty))

    @item.command(name="remove", description="Remove an item: used up, sold, lost…")
    @app_commands.describe(name="Which item", amount="How many (default: all of them)",
                           character="GM: another character's item", stash="From the party stash")
    @app_commands.autocomplete(name=item_ac, character=owner_ac)
    async def item_remove(self, interaction: discord.Interaction, name: str,
                          amount: Optional[app_commands.Range[int, 1, 1_000_000]] = None,
                          character: Optional[str] = None, stash: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        owner = await self._owner(interaction, campaign, character, stash)
        item = await self._item(campaign, owner, name, amount, lang)
        qty = amount or item.qty
        left = await self.db.take_item(item, qty)
        await self._send(interaction, t(lang, "{who} loses **{item}** ({n} left).", who=self._who(lang, owner, True),
                                        item=fmt_item(qty, item.name), n=left))

    async def _item(self, campaign: Campaign, owner: Optional[Character], name: str, amount: Optional[int],
                    lang: str):
        item = await self.db.get_item(campaign.id, owner.id if owner else None, " ".join(name.split()))
        if not item:
            raise UserError(t(lang, "{who} has no **{item}**.", who=self._who(lang, owner), item=name))
        if amount and amount > item.qty:
            raise UserError(t(lang, "{who} only has **{item}**.", who=self._who(lang, owner),
                              item=fmt_item(item.qty, item.name)))
        return item

    @item.command(name="give", description="Give an item to another character or into the party stash")
    @app_commands.describe(name="Which item", to="Character or party stash", amount="How many (default 1)")
    @app_commands.autocomplete(name=item_ac, to=owner_ac)
    async def item_give(self, interaction: discord.Interaction, name: str, to: str,
                        amount: app_commands.Range[int, 1, 1_000_000] = 1):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        giver = await self._active(interaction, campaign)
        target = await self._target(campaign, to)
        if target and target.id == giver.id:
            raise UserError("That's your own character.")
        item = await self._item(campaign, giver, name, amount, lang)
        await self.db.take_item(item, amount)
        await self.db.add_item(campaign.id, target.id if target else None, item.name, amount, item.note)
        await self._send(interaction, t(lang, "**{giver}** gives **{item}** to {target}.", giver=giver.name,
                                        item=fmt_item(amount, item.name), target=self._who(lang, target)))

    @item.command(name="take", description="Take an item out of the party stash")
    @app_commands.describe(name="Which item", amount="How many (default 1)")
    @app_commands.autocomplete(name=stash_item_ac)
    async def item_take(self, interaction: discord.Interaction, name: str,
                        amount: app_commands.Range[int, 1, 1_000_000] = 1):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        taker = await self._active(interaction, campaign)
        item = await self._item(campaign, None, name, amount, lang)
        left = await self.db.take_item(item, amount)
        await self.db.add_item(campaign.id, taker.id, item.name, amount, item.note)
        await self._send(interaction, t(lang, "**{taker}** takes **{item}** from the party stash ({n} left).",
                                        taker=taker.name, item=fmt_item(amount, item.name), n=left))

    # ------------------------------------------------------------------ /money

    @money.command(name="add", description="Add money to your character, or to the party stash")
    @app_commands.describe(amount="How much", currency="e.g. gold, credits, € (default: the one you use)",
                           character="GM: give it to another character", stash="Into the party stash")
    @app_commands.autocomplete(currency=currency_ac, character=owner_ac)
    async def money_add(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1_000_000_000],
                        currency: Optional[str] = None, character: Optional[str] = None, stash: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        owner = await self._owner(interaction, campaign, character, stash)
        cur = await self._currency(campaign, owner, currency)
        total = await self.db.change_money(campaign.id, owner.id if owner else None, cur, amount)
        await self._send(interaction, t(lang, "{who} gets **{money}** (now {total}).",
                                        who=self._who(lang, owner, True),
                                        money=f"{amount:,} {cur}", total=f"{total:,} {cur}"))

    async def _pay(self, campaign: Campaign, owner: Optional[Character], cur: str, amount: int, lang: str) -> int:
        have = (await self.db.get_money(campaign.id, owner.id if owner else None)).get(cur, 0)
        if have < amount:
            raise UserError(t(lang, "{who} only has {money}.", who=self._who(lang, owner), money=f"{have:,} {cur}"))
        return await self.db.change_money(campaign.id, owner.id if owner else None, cur, -amount)

    @money.command(name="spend", description="Spend money from your character, or from the party stash")
    @app_commands.describe(amount="How much", currency="Which currency (default: the one you use)",
                           character="GM: another character's money", stash="From the party stash")
    @app_commands.autocomplete(currency=currency_ac, character=owner_ac)
    async def money_spend(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1_000_000_000],
                          currency: Optional[str] = None, character: Optional[str] = None, stash: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        owner = await self._owner(interaction, campaign, character, stash)
        cur = await self._currency(campaign, owner, currency)
        left = await self._pay(campaign, owner, cur, amount, lang)
        await self._send(interaction, t(lang, "{who} spends **{money}** ({left} left).",
                                        who=self._who(lang, owner, True),
                                        money=f"{amount:,} {cur}", left=f"{left:,} {cur}"))

    @money.command(name="give", description="Give money to another character or into the party stash")
    @app_commands.describe(amount="How much", to="Character or party stash", currency="Which currency")
    @app_commands.autocomplete(to=owner_ac, currency=currency_ac)
    async def money_give(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1_000_000_000],
                         to: str, currency: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        giver = await self._active(interaction, campaign)
        target = await self._target(campaign, to)
        if target and target.id == giver.id:
            raise UserError("That's your own character.")
        cur = await self._currency(campaign, giver, currency)
        await self._pay(campaign, giver, cur, amount, lang)
        await self.db.change_money(campaign.id, target.id if target else None, cur, amount)
        await self._send(interaction, t(lang, "**{giver}** gives **{money}** to {target}.", giver=giver.name,
                                        money=f"{amount:,} {cur}", target=self._who(lang, target)))

    @money.command(name="take", description="Take money out of the party stash")
    @app_commands.describe(amount="How much", currency="Which currency")
    @app_commands.autocomplete(currency=currency_ac)
    async def money_take(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1_000_000_000],
                         currency: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        taker = await self._active(interaction, campaign)
        cur = await self._currency(campaign, None, currency)
        left = await self._pay(campaign, None, cur, amount, lang)
        await self.db.change_money(campaign.id, taker.id, cur, amount)
        await self._send(interaction, t(lang, "**{taker}** takes **{money}** from the party stash ({left} left).",
                                        taker=taker.name, money=f"{amount:,} {cur}", left=f"{left:,} {cur}"))

    # ------------------------------------------------------------------ /inventory

    @app_commands.command(name="inventory", description="Show a character's items and money, or the party stash")
    @app_commands.describe(whose="Character or party stash (default: your active character)",
                           public="Post it for everyone")
    @app_commands.autocomplete(whose=owner_ac)
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction, whose: Optional[str] = None, public: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        lang = campaign.language
        if whose == STASH:
            owner = None
        elif whose:
            owner = await self._find(campaign, whose)
        else:
            owner = await self._active(interaction, campaign)
        owner_id = owner.id if owner else None
        items = await self.db.list_items(campaign.id, owner_id)
        purse = await self.db.get_money(campaign.id, owner_id)
        title = t(lang, "Inventory of {name}", name=owner.name) if owner else t(lang, "Party stash")
        e = discord.Embed(title=title, color=(owner.color if owner and owner.color is not None else COLOR_INFO))
        if owner and owner.avatar_url:
            e.set_thumbnail(url=owner.avatar_url)
        e.description = "\n".join(item_lines(items, lang)) if items else t(lang, "*No items yet.*")
        e.add_field(name=t(lang, "Money"), value=fmt_money(purse) or "—", inline=False)
        e.set_footer(text=t(lang, "/item add · /item give · /money add · /money give"))
        await interaction.response.send_message(embed=e, ephemeral=not public)


async def setup(bot):
    await bot.add_cog(Inventory(bot))
