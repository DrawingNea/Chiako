"""Builds the end-of-session recap from the roll log and the event log."""
from __future__ import annotations

import discord

from . import clock
from .db import Campaign, Database, Session
from .stats import by_user, summarize

MAX_MOMENTS = 15


def duration(seconds: int) -> str:
    h, m = divmod(max(0, seconds) // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m} min"


def medal(i: int) -> str:
    return f"{i + 1}."


async def recap_embed(db: Database, campaign: Campaign, session: Session) -> discord.Embed:
    end = session.ended_at or clock.now()
    rows = await db.roll_rows(guild_id=campaign.guild_id, campaign_id=campaign.id,
                              start=session.started_at, end=end)
    events = await db.list_events(campaign.id, session.started_at, end)
    total = summarize(rows)
    users = by_user(rows)

    title = f"Session {session.number}" + (f": {session.title}" if session.title else "")
    status = "" if session.ended_at else " · still running"
    e = discord.Embed(title=title[:256], color=discord.Color.dark_gold(),
                      description=f"<t:{session.started_at}:f> · {duration(end - session.started_at)}{status}")

    if total.rolls:
        dice_line = (f"{total.rolls} roll{'s' if total.rolls != 1 else ''} · "
                     f"{total.dice} {'die' if total.dice == 1 else 'dice'}")
        if total.d20:
            dice_line += (f" · {total.nat20} natural 20{'s' if total.nat20 != 1 else ''}"
                          f" · {total.nat1} natural 1{'s' if total.nat1 != 1 else ''}")
        pool_successes = sum(p.successes for p in total.pools.values())
        if total.pools:
            dice_line += f" · {pool_successes} successes"
        e.add_field(name="Dice", inline=False, value=dice_line)

        highlights = []
        rated = [(uid, s.luck) for uid, s in users.items() if s.dice >= 3]  # sessions are short
        if len(rated) >= 2:
            lucky = max(rated, key=lambda x: x[1])
            unlucky = min(rated, key=lambda x: x[1])
            highlights.append(f"Luckiest: <@{lucky[0]}> (dice {lucky[1]:+.1f}% vs. average)")
            highlights.append(f"Unluckiest: <@{unlucky[0]}> (dice {unlucky[1]:+.1f}% vs. average)")
        if total.best:
            b = total.best
            highlights.append(f"Biggest roll: **{b.total}** by <@{b.user_id}>" + (f" ({b.label})" if b.label else ""))
        crits = sorted(((uid, s.nat20) for uid, s in users.items() if s.nat20), key=lambda x: -x[1])
        if crits:
            highlights.append(f"Most crits: <@{crits[0][0]}> ({crits[0][1]})")
        if highlights:
            e.add_field(name="Highlights", value="\n".join(highlights), inline=False)
    else:
        e.add_field(name="Dice", value="No rolls this session.", inline=False)

    story = [ev for ev in events if ev.kind != "xp"]
    if story:
        lines = [f"<t:{ev.created_at}:t> · {ev.text}" for ev in story[:MAX_MOMENTS]]
        if len(story) > MAX_MOMENTS:
            lines.append(f"-# …and {len(story) - MAX_MOMENTS} more")
        e.add_field(name="Key moments", value="\n".join(lines)[:1024], inline=False)

    xp_total = sum(ev.value or 0 for ev in events if ev.kind == "xp")
    if xp_total:
        e.add_field(name="XP awarded", value=f"{xp_total:,} XP in total", inline=True)
    if users:
        e.add_field(name="At the table", value=" ".join(f"<@{u}>" for u in users)[:1024], inline=True)
    return e
