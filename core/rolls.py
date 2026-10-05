"""Turning a roll request into an embed plus log data. Shared by /r, inline rolls, group checks and initiative."""
from __future__ import annotations

import re
from typing import Optional

import discord

from dice.engine import DiceError, fate_ladder, split_label
from dice.systems import three_d20_check

from .helpers import roll_embed, successes_text, three_d20_embed
from .i18n import t
from .sheet import COUNT_JOIN, RollEnv
from .stats import check_profile, roll_profile

_SINGLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def campaign_check(env: RollEnv, text: str, modifier: int = 0) -> tuple[str, int]:
    """
    With campaign dice rules, a dice-free check becomes that many campaign dice:
    'shooting & dex' (4 + 3) -> '7d10!>=8 # Shooting & Dex'. The modifier adds dice.
    Returns (text, modifier left to apply); anything else is returned unchanged.
    """
    expr, label = split_label(text)
    count = env.dice_count(expr)
    if count is None:
        return text, modifier
    count += modifier
    if count < 1:
        raise DiceError(f"That's {count} dice, so there's nothing to roll.")
    if not label:
        if _SINGLE_NAME.match(expr):
            label = env.label_for(expr.lower())
        elif re.search(r"[A-Za-z]", expr):
            label = COUNT_JOIN.sub(" & ", expr)
            label = re.sub(r"[A-Za-z_][A-Za-z0-9_]*", lambda m: m.group(0).replace("_", " ").title(), label)
            label = " ".join(label.split())
        if label and modifier:
            label += f" {modifier:+}"
    return env.rules.expression(count) + (f" # {label}" if label else ""), 0


def build_roll(env: RollEnv, user, text: str, advantage: Optional[str] = None, modifier: int = 0,
               pbta: bool = False) -> tuple[discord.Embed, dict]:
    """
    Roll `text` for this user and build the embed.
    Returns (embed, data). data holds the log fields plus:
      summary: short result text ("**17**", "QL 2"), success: bool or None (3d20 only)
      phrase: the result in a few words for inline sentences ("17", "2 Successes", "QL 2")
      kind, setting, faces, expected: details for dice statistics (see core.stats.roll_profile)
    """
    character = env.character
    skill = env.skill_3d20(text)
    if skill:
        attrs = [(a.upper(), env.resolve_stat(a)) for a in skill.attributes]
        res = three_d20_check(attrs, skill.points, modifier)
        title = env.label_for(skill.name)
        embed = three_d20_embed(res, title, user, character, env.lang)
        if res.botch:
            summary = "Botch"
        elif res.success:
            summary = f"QL {res.quality}" + (" (critical)" if res.critical else "")
        else:
            summary = f"failed by {-res.remaining}"
        return embed, dict(expression=f"3d20:{skill.name}", label=title, total=res.remaining, natural=None,
                           summary=summary, success=res.success, phrase=summary, **check_profile(res))

    if env.rules and not pbta:
        text, modifier = campaign_check(env, text, modifier)

    if modifier:
        expr, _, label = text.partition("#")
        text = f"{expr.strip()} {'+' if modifier > 0 else '-'} {abs(modifier)}" + (f" #{label}" if label else "")
        if not label:
            text += f" # {expr.strip().replace('_', ' ').title()}"
    result = env.roll(text, advantage)
    embed = roll_embed(result, user, character, pbta=pbta, lang=env.lang)
    nat = result.natural_d20
    return embed, dict(expression=result.expression, label=result.label, total=result.total, natural=nat,
                       summary=f"**{result.total}**", success=None, phrase=result_phrase(result, env.lang),
                       **roll_profile(result))


def result_phrase(result, lang: str = "en") -> str:
    """The result in a few words, e.g. '17', '+2 Fair', '2 Successes', 'No successes'."""
    total = result.total
    if result.is_pool:
        return successes_text(total, lang)
    if result.has_fate:
        return f"{total:+} {t(lang, fate_ladder(total))}"
    return f"{total}"


async def log_roll(db, data: dict, *, guild_id, channel_id, campaign, user_id, env: RollEnv, secret=False):
    await db.log_roll(
        guild_id=guild_id, channel_id=channel_id, campaign_id=campaign.id if campaign else None,
        user_id=user_id, character_id=env.character.id if env.character else None, secret=secret,
        expression=data["expression"], label=data["label"], total=data["total"], natural=data["natural"],
        kind=data.get("kind"), setting=data.get("setting"), faces=data.get("faces"), expected=data.get("expected"),
    )
    nat = data.get("natural")
    if campaign and guild_id and not secret and nat in (1, 20):
        who = env.character.name if env.character else f"<@{user_id}>"
        what = data.get("label") or data["expression"]
        await db.add_event(campaign_id=campaign.id, guild_id=guild_id, kind="crit" if nat == 20 else "fumble",
                           text=f"{who} rolled a natural {nat} on {what}", user_id=user_id, value=nat)
