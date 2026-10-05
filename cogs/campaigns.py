"""Campaigns: group channels, set the GM and GM role, toggle character webhooks."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from dice.engine import DiceError, roll
from core.db import Campaign, IntegrityError
from core.helpers import COLOR_INFO, UserError, channel_key, get_campaign, report_error, require_campaign, require_gm
from core.i18n import LANGUAGES, t
from core.sheet import DiceRules
from core.sheetcard import EXAMPLE_LAYOUT, parse_layout


def dice_rules_text(rules: DiceRules, bot_user, lang: str = "en") -> str:
    mention = f"<@{bot_user.id}>" if bot_user else "@bot"
    return "\n".join([
        rules.describe(lang), "",
        t(lang, "A skill whose value is a number rolls that many dice, e.g. `/skill add shooting 5`."),
        t(lang, "**Roll:** `/check shooting` · `/check shooting & dex` · `/check 5`"),
        t(lang, "**Or just talk to the bot:** {me} `roll shooting & dex` · {me} `w5`", me=mention),
    ])


class SheetLayoutModal(discord.ui.Modal):
    """The GM writes the character sheet layout: one section per line."""

    def __init__(self, cog: "Campaigns", campaign: Campaign):
        super().__init__(title="Character sheet layout")
        self.cog, self.campaign = cog, campaign
        self.layout = discord.ui.TextInput(
            label="One section per line: Section: stat, stat", style=discord.TextStyle.paragraph,
            default=campaign.sheet_layout or EXAMPLE_LAYOUT, max_length=2000,
            placeholder=EXAMPLE_LAYOUT)
        self.add_item(self.layout)

    async def on_submit(self, interaction: discord.Interaction):
        parse_layout(self.layout.value)  # raises a UserError explaining any mistake
        await self.cog.db.update_campaign(self.campaign.id, sheet_layout=self.layout.value.strip())
        await interaction.response.send_message(
            t(self.campaign.language, "Sheet layout saved for **{campaign}**. Have a look with `/char show`.",
              campaign=self.campaign.name), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_error(interaction, error)


class Campaigns(commands.Cog):
    campaign = app_commands.Group(name="campaign", description="Set up and manage campaigns", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def campaign_autocomplete(self, interaction: discord.Interaction, current: str):
        campaigns = await self.db.list_campaigns(interaction.guild_id)
        return [Choice(name=c.name, value=c.name) for c in campaigns if current.lower() in c.name.lower()][:25]

    @campaign.command(name="create", description="Create a campaign in this channel. You become the GM.")
    @app_commands.describe(name="Campaign name")
    async def create(self, interaction: discord.Interaction, name: str):
        name = name.strip()[:64]
        existing = await get_campaign(self.db, interaction.channel)
        if existing:
            raise UserError(f"This channel already belongs to **{existing.name}**. Use `/campaign unlink` first.")
        try:
            c = await self.db.create_campaign(interaction.guild_id, name, interaction.user.id,
                                              channel_key(interaction.channel))
        except IntegrityError:
            raise UserError(f"A campaign called **{name}** already exists here. Use `/campaign link` to add this channel.")
        e = discord.Embed(title=f"{c.name}", color=COLOR_INFO, description=(
            f"Campaign created! {interaction.user.mention} is the GM. 🌸\n\n"
            "**Players, next steps:**\n"
            "1. `/char create name:<your hero>`\n"
            "2. `/stat bulk str=3, dex=2, con=1, level=1`\n"
            "3. `/skill add stealth 1d20+dex+2`\n"
            "4. `/r stealth`\n\n"
            "Use `/campaign link` to add more channels (threads are included automatically)."
        ))
        await interaction.response.send_message(embed=e)

    @campaign.command(name="link", description="Add this channel to an existing campaign (GM only)")
    @app_commands.describe(name="Campaign name")
    @app_commands.autocomplete(name=campaign_autocomplete)
    async def link(self, interaction: discord.Interaction, name: str):
        c = await self.db.get_campaign_by_name(interaction.guild_id, name)
        if not c:
            raise UserError(f"No campaign called **{name}** here.")
        require_gm(interaction.user, c)
        await self.db.link_channel(channel_key(interaction.channel), c.id)
        await interaction.response.send_message(f"This channel now belongs to **{c.name}**.")

    @campaign.command(name="unlink", description="Remove this channel from its campaign (GM only)")
    async def unlink(self, interaction: discord.Interaction):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        await self.db.unlink_channel(channel_key(interaction.channel))
        await interaction.response.send_message(f"This channel is no longer part of **{c.name}**. "
                                                "Characters and data are kept.")

    @campaign.command(name="info", description="Show this channel's campaign")
    async def info(self, interaction: discord.Interaction):
        c = await require_campaign(self.db, interaction.channel)
        channels = await self.db.campaign_channels(c.id)
        characters = await self.db.list_characters(c.id)
        e = discord.Embed(title=f"{c.name}", color=COLOR_INFO)
        e.add_field(name="GM", value=f"<@{c.gm_user_id}>")
        e.add_field(name="GM role", value=f"<@&{c.gm_role_id}>" if c.gm_role_id else "—")
        e.add_field(name="Character webhooks", value="on" if c.use_webhooks else "off")
        e.add_field(name="Initiative roll", value=f"`{c.init_formula}`")
        e.add_field(name="Time zone", value=c.timezone)
        rules = DiceRules.of(c)
        e.add_field(name="Dice rules", value=rules.describe(c.language) if rules else "— (`/campaign dice`)",
                    inline=False)
        e.add_field(name="Language", value=LANGUAGES.get(c.language, c.language))
        e.add_field(name="Channels", value=" ".join(f"<#{ch}>" for ch in channels)[:1024] or "—", inline=False)
        if characters:
            by_owner: dict[int, list[str]] = {}
            for ch in characters:
                by_owner.setdefault(ch.owner_id, []).append(ch.name)
            text = "\n".join(f"<@{o}>: {', '.join(names)}" for o, names in by_owner.items())
            e.add_field(name=f"Characters ({len(characters)})", value=text[:1024], inline=False)
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    @campaign.command(name="gm-role", description="Give a role GM powers in this campaign (GM only)")
    @app_commands.describe(role="Role with GM powers (leave empty to remove)")
    async def gm_role(self, interaction: discord.Interaction, role: Optional[discord.Role] = None):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        await self.db.update_campaign(c.id, gm_role_id=role.id if role else None)
        await interaction.response.send_message(
            f"GM role set to {role.mention}." if role else "GM role removed.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @campaign.command(name="transfer", description="Make someone else the main GM (GM only)")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        await self.db.update_campaign(c.id, gm_user_id=member.id)
        await interaction.response.send_message(f"{member.mention} is now the GM of **{c.name}**.")

    @campaign.command(name="webhooks", description="Post rolls under the character's name and avatar (GM only)")
    async def webhooks(self, interaction: discord.Interaction, enabled: bool):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        await self.db.update_campaign(c.id, use_webhooks=int(enabled))
        note = " The bot needs the **Manage Webhooks** permission for this." if enabled else ""
        await interaction.response.send_message(f"Character webhooks {'enabled' if enabled else 'disabled'}.{note}")

    @campaign.command(name="init-formula", description="Default initiative roll for characters (GM only)")
    @app_commands.describe(formula="e.g. 1d20+dex, 1d10+ini, 2d6. A character's own 'initiative' skill wins")
    async def init_formula(self, interaction: discord.Interaction, formula: str):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        formula = formula.strip()
        try:
            roll(formula, stat_resolver=lambda name: 0, name_resolver=lambda name: "0")
        except DiceError as e:
            raise UserError(f"That formula doesn't work: {e}")
        await self.db.update_campaign(c.id, init_formula=formula)
        await interaction.response.send_message(f"Initiative is now rolled with `{formula}`.")

    @campaign.command(name="dice", description="Dice rules for /check: which die, successes, exploding (GM only)")
    @app_commands.describe(
        sides="Which die to roll, e.g. 10 for d10 (0 turns the dice rules off)",
        success="A die at or above this counts as a success (0 = add the dice up instead)",
        explode="A die at or above this rolls an extra die, e.g. 10 (0 = no exploding)",
        cancel="A die at or below this cancels a success, e.g. 1 (0 = off)",
    )
    async def dice(self, interaction: discord.Interaction,
                   sides: Optional[app_commands.Range[int, 0, 1000]] = None,
                   success: Optional[app_commands.Range[int, 0, 1000]] = None,
                   explode: Optional[app_commands.Range[int, 0, 1000]] = None,
                   cancel: Optional[app_commands.Range[int, 0, 1000]] = None):
        c = await require_campaign(self.db, interaction.channel)
        if sides is None and success is None and explode is None and cancel is None:
            rules = DiceRules.of(c)
            text = (dice_rules_text(rules, getattr(interaction.client, "user", None), c.language) if rules else
                    t(c.language, "No dice rules yet: `/check` rolls skill formulas as written.\n"
                                  "The GM can set them up, e.g. `/campaign dice sides:10 success:8 explode:10`."))
            await interaction.response.send_message(embed=discord.Embed(
                title=t(c.language, "Dice rules · {campaign}", campaign=c.name), description=text, color=COLOR_INFO))
            return
        require_gm(interaction.user, c)

        if sides == 0:
            fields = dict(dice_sides=None, dice_explode=None, dice_success=None, dice_cancel=None)
        else:
            fields = {}
            for key, value in (("dice_sides", sides), ("dice_success", success), ("dice_explode", explode),
                               ("dice_cancel", cancel)):
                if value is not None:
                    fields[key] = value or None
            merged = {k: fields.get(k, getattr(c, k)) for k in ("dice_sides", "dice_explode", "dice_success",
                                                                "dice_cancel")}
            if not merged["dice_sides"]:
                raise UserError("Pick the die first, e.g. `/campaign dice sides:10 success:8 explode:10`.")
            rules = DiceRules(merged["dice_sides"], merged["dice_explode"], merged["dice_success"],
                              merged["dice_cancel"])
            try:
                roll(rules.expression(5))
            except DiceError as e:
                raise UserError(f"Those rules don't work: {e}")
            if rules.success and rules.success > rules.sides:
                raise UserError(f"A d{rules.sides} can never roll {rules.success}, so nothing would succeed.")
        await self.db.update_campaign(c.id, **fields)
        c = await self.db.get_campaign(c.id)
        rules = DiceRules.of(c)
        text = dice_rules_text(rules, getattr(interaction.client, "user", None), c.language) if rules else \
            t(c.language, "Dice rules are off: `/check` rolls skill formulas as written again.")
        await interaction.response.send_message(embed=discord.Embed(
            title=t(c.language, "Dice rules · {campaign}", campaign=c.name), description=text, color=COLOR_INFO))

    @campaign.command(name="language", description="The language the bot speaks in this campaign (GM only)")
    @app_commands.describe(language="English or Deutsch")
    @app_commands.choices(language=[Choice(name=name, value=code) for code, name in LANGUAGES.items()])
    async def language(self, interaction: discord.Interaction, language: Choice[str]):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        await self.db.update_campaign(c.id, language=language.value)
        await interaction.response.send_message(
            t(language.value, "This campaign now speaks **{language}**.", language=LANGUAGES[language.value]))

    @campaign.command(name="sheet", description="Lay out the character sheet card for your game (GM only)")
    @app_commands.describe(reset="Go back to the automatic layout")
    async def sheet(self, interaction: discord.Interaction, reset: bool = False):
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        if reset:
            await self.db.update_campaign(c.id, sheet_layout=None)
            await interaction.response.send_message(t(c.language, "The sheet layout is back to automatic."),
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(SheetLayoutModal(self, c))

    @campaign.command(name="timezone", description="Time zone for dates you type in /schedule (GM only)")
    @app_commands.describe(name="e.g. Europe/Berlin, America/New_York, UTC")
    async def timezone(self, interaction: discord.Interaction, name: str):
        from core.scheduling import get_zone
        c = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, c)
        zone = get_zone(name.strip())
        await self.db.update_campaign(c.id, timezone=zone.key)
        await interaction.response.send_message(
            f"Time zone set to **{zone.key}**. Players still see times in their own zone.")

    @timezone.autocomplete("name")
    async def timezone_ac(self, interaction: discord.Interaction, current: str):
        from zoneinfo import available_timezones
        common = ["UTC", "Europe/Berlin", "Europe/London", "Europe/Vienna", "Europe/Zurich", "Europe/Paris",
                  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
                  "Australia/Sydney", "Asia/Tokyo"]
        if not current:
            return [Choice(name=z, value=z) for z in common]
        try:
            zones = sorted(available_timezones())
        except Exception:
            zones = common
        return [Choice(name=z, value=z) for z in zones if current.lower() in z.lower()][:25]


async def setup(bot):
    await bot.add_cog(Campaigns(bot))
