"""Shared Discord helpers used by all cogs."""
from __future__ import annotations

import logging
import re
from typing import Optional, Union

import discord
from discord.utils import MISSING

from dice.engine import DiceError, RollResult, fate_ladder
from dice.systems import ThreeD20Result, pbta_outcome

from .db import Campaign, Character, Database
from .i18n import plural, t
from .sheet import DiceRules, RollEnv, Sheet

log = logging.getLogger("dicebot")

COLOR_DEFAULT = discord.Color.blurple()
COLOR_CRIT = discord.Color.green()
COLOR_FUMBLE = discord.Color.red()
COLOR_SECRET = discord.Color.dark_grey()
COLOR_INFO = discord.Color.gold()


class UserError(Exception):
    """An error caused by the user; the message is shown to them."""


# ------------------------------------------------------------------ errors

async def report_error(interaction: discord.Interaction, error: Exception):
    if isinstance(error, discord.app_commands.CommandInvokeError):
        error = error.original
    if isinstance(error, (UserError, DiceError)):
        text = f"{error}"
    elif isinstance(error, discord.app_commands.CheckFailure):
        text = "You can't use that command here."
    else:
        log.exception("Unhandled error", exc_info=error)
        text = "Something went wrong on my side. Check the bot logs."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


class BaseView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        await report_error(interaction, error)


# ------------------------------------------------------------------ campaigns & characters

def channel_key(channel) -> int:
    """Threads belong to the campaign of their parent channel."""
    if isinstance(channel, discord.Thread) and channel.parent_id:
        return channel.parent_id
    return channel.id


async def get_campaign(db: Database, channel) -> Optional[Campaign]:
    if channel is None:
        return None
    return await db.get_campaign_by_channel(channel_key(channel))


async def require_campaign(db: Database, channel) -> Campaign:
    campaign = await get_campaign(db, channel)
    if not campaign:
        raise UserError("This channel isn't part of a campaign yet. The GM can run `/campaign create` here.")
    return campaign


def is_gm(member: Union[discord.Member, discord.User], campaign: Campaign) -> bool:
    if member.id == campaign.gm_user_id:
        return True
    if isinstance(member, discord.Member):
        if campaign.gm_role_id and any(r.id == campaign.gm_role_id for r in member.roles):
            return True
        if member.guild_permissions.manage_guild:
            return True
    return False


def require_gm(member, campaign: Campaign):
    if not is_gm(member, campaign):
        raise UserError("Only the GM of this campaign can do that.")


async def load_sheet(db: Database, character: Character) -> Sheet:
    return Sheet(character, await db.get_stats(character.id), await db.get_skills(character.id))


async def load_env(db: Database, campaign: Optional[Campaign], user_id: int, guild_id: Optional[int]) -> RollEnv:
    sheet = None
    if campaign:
        character = await db.get_active_character(campaign.id, user_id)
        if character:
            sheet = await load_sheet(db, character)
    macros = await db.get_roll_macros(campaign.id if campaign else None, guild_id, user_id)
    return RollEnv(sheet, macros, DiceRules.of(campaign), lang=campaign.language if campaign else "en")


async def require_character(db: Database, interaction: discord.Interaction) -> tuple[Campaign, Character]:
    campaign = await require_campaign(db, interaction.channel)
    character = await db.get_active_character(campaign.id, interaction.user.id)
    if not character:
        raise UserError("You don't have an active character in this campaign. Use `/char create` or `/char use`.")
    return campaign, character


# ------------------------------------------------------------------ embeds

def _set_identity(embed: discord.Embed, user, character: Optional[Character]):
    if character:
        embed.set_author(name=character.name, icon_url=character.avatar_url or user.display_avatar.url)
        embed.set_footer(text=f"played by {user.display_name}")
    else:
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)


def roll_embed(result: RollResult, user, character: Optional[Character], *, pbta: bool = False,
               lang: str = "en") -> discord.Embed:
    """
    Normal rolls, in the same layout as success pools:
        Results for Evi                              (title, avatar as thumbnail)
        -# Stealth · 1 × 20-sided die + dex(4) + prof(2)    (label and the roll in words, with stat values)
        ## `14`                                      (each die in a code box; dropped dice struck out)
        # 20                                      (the total)
    """
    if result.is_pool:
        return pool_embed(result, user, character, lang=lang)
    nat = result.natural_d20
    color = COLOR_CRIT if nat == 20 else COLOR_FUMBLE if nat == 1 else COLOR_DEFAULT

    formula = _plain_formula(result, lang)
    info = [f"**{result.label}**"] if result.label else []
    info.append(formula)
    lines = ["-# " + " · ".join(info)]
    dice_groups = []
    for term in result.terms:
        waves: dict[int, list] = {}
        for d in term.dice:
            waves.setdefault(d.wave, []).append(d)
        shown = []
        for w in sorted(waves):
            faces = [_FATE_FACES.get(d.value, str(d.value)) if term.fate else f"`{d.value}`" for d in waves[w]]
            shown.append(" ".join(f if d.kept else f"~~{f}~~" for f, d in zip(faces, waves[w])))
        dice_groups.append("  -  ".join(shown))
    if dice_groups:
        lines.append("## " + "  ·  ".join(dice_groups))

    if result.has_fate:
        lines.append(f"# {result.total:+} · {t(lang, fate_ladder(result.total))}")
    else:
        lines.append(f"# {result.total}")
    if pbta:
        emoji, text = pbta_outcome(result.total)
        lines.append(f"### {t(lang, text)} {emoji}".rstrip())
    if nat == 20:
        lines.append("### " + t(lang, "Natural 20!") + " 🍀")
    elif nat == 1:
        lines.append("### " + t(lang, "Natural 1!") + " 💤")
    if result.advantage and not result.advantage_applied:
        lines.append("-# " + t(lang, "(no single d20 found, so advantage/disadvantage was ignored)"))

    description = "\n".join(lines)
    if len(description) > 4000:
        description = description[:4000] + "…"
    embed = discord.Embed(description=description, color=color)
    _results_header(embed, user, character, lang)
    return embed


_FATE_FACES = {-1: "`−`", 0: "`0`", 1: "`+`"}
_KEEP_TEXT = {"kh": "keep highest {n}", "kl": "keep lowest {n}", "dh": "drop highest {n}", "dl": "drop lowest {n}"}


def _explode_text(term, lang: str = "en") -> str:
    if term.explode >= term.sides:
        return t(lang, "{sides}s explode", sides=term.sides)
    return t(lang, "{n}+ explode", n=term.explode)


def describe_dice(term, *, explode: bool = True, lang: str = "en") -> str:
    """'4d10!kh3' -> '4 × 10-sided dice (keep highest 3, 10s explode)'"""
    n = term.count
    if term.sides == 20 and n == 2 and term.keep in (("kh", 1), ("kl", 1)) and not term.reroll and not term.explode:
        return t(lang, "1 × 20-sided die with advantage" if term.keep[0] == "kh"
                 else "1 × 20-sided die with disadvantage")
    if term.fate:
        text = plural(lang, n, "{n} × Fate die", "{n} × Fate dice")
    else:
        text = plural(lang, n, "{n} × {sides}-sided die", "{n} × {sides}-sided dice", sides=term.sides)
    extras = []
    if term.keep:
        extras.append(t(lang, _KEEP_TEXT[term.keep[0]], n=term.keep[1]))
    if term.reroll is not None:
        extras.append(t(lang, "reroll 1s once") if term.reroll == 1 else t(lang, "reroll ≤ {n} once", n=term.reroll))
    if explode and term.explode:
        extras.append(_explode_text(term, lang))
    return text + (f" ({', '.join(extras)})" if extras else "")


def _plain_formula(result: RollResult, lang: str = "en") -> str:
    """The roll in words: '1d20 [14] + dex(4)' -> '1 × 20-sided die + dex(4)'."""
    text, out, pos = result.breakdown, [], 0
    for term in result.terms:
        m = re.compile(re.escape(term.notation) + r" \[[^\]]*\]").search(text, pos)
        if not m:  # e.g. dice that only set another group's count, like the 1d4 in (1d4)d6
            continue
        out += [text[pos:m.start()], describe_dice(term, lang=lang)]
        pos = m.end()
    out.append(text[pos:])
    return " ".join("".join(out).split())


def _results_header(embed: discord.Embed, user, character: Optional[Character], lang: str = "en"):
    """'Results for Evi' (the character, or the user without one) as the title, with their avatar as thumbnail."""
    embed.title = t(lang, "Results for {name}", name=character.name if character else user.display_name)[:256]
    embed.set_thumbnail(url=(character.avatar_url if character else None) or user.display_avatar.url)


_RULE = {">=": "≥", "<=": "≤", ">": ">", "<": "<", "=": "="}


def _pool_die(d) -> str:
    """Each die in its own code box. The line is a heading (already bold), so successes are underlined;
    dice that cancel a success and dropped dice are struck out."""
    if not d.kept or d.outcome < 0:
        return f"~~`{d.value}`~~"
    if d.outcome > 0:
        return f"__`{d.value}`__"
    return f"`{d.value}`"


def successes_text(total: int, lang: str = "en") -> str:
    """'2 Successes ✨', 'No successes 💤' or 'Botch (-1) 💤'."""
    if total > 0:
        return plural(lang, total, "{n} Success", "{n} Successes") + " ✨"
    return (t(lang, "No successes") if total == 0 else t(lang, "Botch ({n})", n=total)) + " 💤"


def pool_embed(result: RollResult, user, character: Optional[Character], *, lang: str = "en") -> discord.Embed:
    """
    Success pools in the classic layout, as an embed:
        Results for Evi                                         (title, avatar as thumbnail)
        -# Pool · 5 × 10-sided dice · success at ≥ 8 · 10s explode
        ## `10` `10` `8` `4` `3`  -  `10` `2`  -  `4` (each die in a code box, successes underlined;
                                                       each "-" group is the next round of exploded dice)
        # 4 Successes
    """
    lines = []
    bonus = 0
    for term in result.terms:
        if not term.pool:
            lines.append(f"-# {describe_dice(term, lang=lang)} → {term.total}")
            continue
        rules = [f"**{result.label}**"] if result.label else []
        rules.append(describe_dice(term, explode=False, lang=lang))
        if term.compare:
            rules.append(t(lang, "success at {rule} {target}", rule=_RULE[term.compare[0]], target=term.compare[1]))
        if term.explode:
            rules.append(_explode_text(term, lang))
        if term.fail is not None:
            rules.append(t(lang, "≤ {n} cancels one", n=term.fail))
        lines.append("-# " + " · ".join(rules))
        waves: dict[int, list] = {}
        for d in term.dice:
            waves.setdefault(d.wave, []).append(d)
        groups = []
        for w in sorted(waves):
            dice = sorted(waves[w], key=lambda d: d.value, reverse=True)
            groups.append(" ".join(_pool_die(d) for d in dice))
        lines.append("## " + "  -  ".join(groups))
        bonus += sum(1 for d in term.dice if d.exploded)

    total = result.total
    lines.append("# " + successes_text(total, lang))
    color = COLOR_CRIT if total > 0 else COLOR_FUMBLE
    if bonus:
        lines.append("-# " + plural(lang, bonus, "{n} bonus die from explosions", "{n} bonus dice from explosions"))

    description = "\n".join(lines)
    if len(description) > 4000:
        description = description[:4000] + "…"
    embed = discord.Embed(description=description, color=color)
    _results_header(embed, user, character, lang)
    return embed


def three_d20_embed(res: ThreeD20Result, title: str, user, character: Optional[Character],
                    lang: str = "en") -> discord.Embed:
    lines = []
    for d in res.dice:
        mark = f"−{d.overshoot}" if d.overshoot else "✓"
        lines.append(f"**{d.attribute}** {d.target} → **{d.roll}** ({mark})")
    mod = " · " + t(lang, "modifier {mod}", mod=f"{res.modifier:+}") if res.modifier else ""
    lines.append("-# " + t(lang, "{points} skill points", points=res.points) + mod)

    if res.botch:
        lines.append("## " + t(lang, "Botch!") + " 💤")
        color = COLOR_FUMBLE
    elif res.critical:
        lines.append("## " + t(lang, "Critical success! QL {ql}", ql=res.quality) + " 🍀")
        color = COLOR_CRIT
    elif res.success:
        lines.append("## " + t(lang, "Success · QL {ql}", ql=res.quality) + " ✨")
        lines.append(plural(lang, res.remaining, "{n} point left", "{n} points left"))
        color = COLOR_DEFAULT
    else:
        lines.append("## " + t(lang, "Failed by {n}", n=-res.remaining))
        color = COLOR_FUMBLE

    embed = discord.Embed(title=f"{title}"[:256], description="\n".join(lines), color=color)
    _set_identity(embed, user, character)
    return embed


# ------------------------------------------------------------------ character webhooks

class WebhookCache:
    """One bot-owned webhook per channel, used to post rolls as the character (name + avatar)."""

    NAME = "DiceBot Characters"

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._hooks: dict[int, discord.Webhook] = {}

    def invalidate(self, channel_id: int):
        self._hooks.pop(channel_id, None)

    async def get(self, channel) -> Optional[tuple[discord.Webhook, object]]:
        thread = MISSING
        if isinstance(channel, discord.Thread):
            thread, channel = channel, channel.parent
        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            return None
        hook = self._hooks.get(channel.id)
        if hook is None:
            if not channel.permissions_for(channel.guild.me).manage_webhooks:
                return None
            try:
                for h in await channel.webhooks():
                    if h.user and h.user.id == self.bot.user.id and h.name == self.NAME:
                        hook = h
                        break
                if hook is None:
                    hook = await channel.create_webhook(name=self.NAME)
            except discord.HTTPException:
                return None
            self._hooks[channel.id] = hook
        return hook, thread


async def send_as(
    interaction: discord.Interaction,
    hooks: WebhookCache,
    campaign: Optional[Campaign],
    character: Optional[Character],
    embed: discord.Embed,
    view: Optional[discord.ui.View] = None,
):
    """Post a roll publicly, as the character via webhook when possible, otherwise as the bot."""
    extra = {"view": view} if view else {}

    if character and campaign and campaign.use_webhooks:
        target = await hooks.get(interaction.channel)
        if target:
            webhook, thread = target
            await interaction.response.defer(ephemeral=True, thinking=True)
            for kwargs in (extra, {}):  # retry without buttons if the webhook refuses components
                try:
                    await webhook.send(
                        embed=embed,
                        username=character.name[:80],
                        avatar_url=character.avatar_url or interaction.user.display_avatar.url,
                        thread=thread,
                        **kwargs,
                    )
                    await interaction.delete_original_response()
                    return
                except discord.NotFound:
                    hooks.invalidate(channel_key(interaction.channel))
                    break
                except discord.HTTPException as e:
                    log.warning("Webhook send failed: %s", e)
            # Webhook failed: post as the bot instead (the deferred reply is ephemeral, so post to the channel)
            await interaction.channel.send(embed=embed, **extra)
            await interaction.delete_original_response()
            return

    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, **extra)
    else:
        await interaction.response.send_message(embed=embed, **extra)
