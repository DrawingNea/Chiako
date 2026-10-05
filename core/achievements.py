"""
Achievements: unlocked per player per server, announced in the channel where they happened.
Secret rolls never count (that would leak a hidden natural 20).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional

import discord

from .db import Database
from .stats import summarize

log = logging.getLogger("dicebot")


@dataclass
class Ctx:
    """Data for one player, loaded once per check."""
    db: Database
    guild_id: int
    user_id: int
    _rows: Optional[list] = None

    async def rows(self):
        if self._rows is None:
            self._rows = await self.db.roll_rows(guild_id=self.guild_id, user_id=self.user_id)
        return self._rows

    async def naturals(self) -> list[int]:
        return [r.natural for r in await self.rows() if r.natural is not None]


@dataclass
class Achievement:
    key: str
    emoji: str
    name: str
    description: str
    check: Callable[[Ctx], Awaitable[bool]]


async def _streak(ctx: Ctx, value: int, length: int) -> bool:
    """`length` natural d20s in a row showing `value`, anywhere in the history."""
    run = 0
    for n in await ctx.naturals():
        run = run + 1 if n == value else 0
        if run >= length:
            return True
    return False


async def _rolls_at_least(ctx: Ctx, n: int) -> bool:
    return len(await ctx.rows()) >= n


async def _nat_count(ctx: Ctx, value: int, n: int) -> bool:
    return (await ctx.naturals()).count(value) >= n


async def _big_total(ctx: Ctx, n: int) -> bool:
    best = summarize(await ctx.rows()).best
    return best is not None and best.total >= n


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_roll", "", "Let's Roll", "Make your first roll.", lambda c: _rolls_at_least(c, 1)),
    Achievement("nat20", "", "Natural Talent", "Roll a natural 20.", lambda c: _nat_count(c, 20, 1)),
    Achievement("nat1", "", "Critical Failure", "Roll a natural 1. It happens to the best of us.",
                lambda c: _nat_count(c, 1, 1)),
    Achievement("double20", "", "Lightning Strikes Twice", "Roll two natural 20s in a row.",
                lambda c: _streak(c, 20, 2)),
    Achievement("cursed", "", "Cursed Dice", "Roll three natural 1s in a row.", lambda c: _streak(c, 1, 3)),
    Achievement("hat_trick", "", "Hat Trick", "Roll ten natural 20s.", lambda c: _nat_count(c, 20, 10)),
    Achievement("overkill", "", "Overkill", "Get a total of 50 or more in a single roll.",
                lambda c: _big_total(c, 50)),
    Achievement("centurion", "", "Centurion", "Make 100 rolls.", lambda c: _rolls_at_least(c, 100)),
    Achievement("dice_goblin", "", "Dice Goblin", "Make 1,000 rolls.", lambda c: _rolls_at_least(c, 1000)),
    Achievement("slayer", "", "Monster Slayer", "Defeat 10 monsters.",
                lambda c: _events(c, "defeat", 10)),
    Achievement("first_kill", "", "First Blood", "Defeat a monster.", lambda c: _events(c, "defeat", 1)),
    Achievement("brink", "", "Back from the Brink", "Get back up after dropping to 0 HP.",
                lambda c: _events(c, "revive", 1)),
    Achievement("seasoned", "", "Seasoned Adventurer", "Reach level 5.",
                lambda c: _events(c, "levelup", 1, min_value=5)),
    Achievement("legend", "", "Living Legend", "Reach level 10.",
                lambda c: _events(c, "levelup", 1, min_value=10)),
    Achievement("best_friend", "", "Best Friend", "Get a companion.",
                lambda c: _companion(c)),
    Achievement("loremaster", "", "Loremaster", "Write 5 campaign notes.", lambda c: _notes(c, 5)),
    Achievement("regular", "", "Regular", "Roll dice in 5 different sessions.", lambda c: _sessions(c, 5)),
]
BY_KEY = {a.key: a for a in ACHIEVEMENTS}


async def _events(ctx: Ctx, kind: str, n: int, min_value: Optional[int] = None) -> bool:
    return await ctx.db.count_events(ctx.guild_id, ctx.user_id, kind, min_value) >= n


async def _companion(ctx: Ctx) -> bool:
    return await ctx.db.count_user_companions(ctx.guild_id, ctx.user_id) > 0


async def _notes(ctx: Ctx, n: int) -> bool:
    return await ctx.db.count_user_notes(ctx.guild_id, ctx.user_id) >= n


async def _sessions(ctx: Ctx, n: int) -> bool:
    return await ctx.db.sessions_attended(ctx.guild_id, ctx.user_id) >= n


class AchievementService:
    def __init__(self, bot):
        self.bot = bot
        self.db: Database = bot.db

    async def check(self, guild_id: Optional[int], user_ids: Iterable[int], channel=None) -> list[tuple[int, Achievement]]:
        """Unlock whatever these players have earned and announce it. Never raises."""
        if not guild_id:
            return []
        unlocked = []
        try:
            for uid in dict.fromkeys(u for u in user_ids if u):
                have = await self.db.unlocked_achievements(guild_id, uid)
                ctx = Ctx(self.db, guild_id, uid)
                for a in ACHIEVEMENTS:
                    if a.key not in have and await a.check(ctx):
                        if await self.db.unlock_achievement(guild_id, uid, a.key):
                            unlocked.append((uid, a))
            if unlocked and channel is not None:
                await channel.send(embed=announce_embed(unlocked),
                                   allowed_mentions=discord.AllowedMentions.none())
        except Exception:  # achievements must never break a command
            log.exception("Achievement check failed")
        return unlocked


def announce_embed(unlocked: list[tuple[int, Achievement]]) -> discord.Embed:
    lines = [f"<@{uid}> earned **{a.name}**: {a.description}" for uid, a in unlocked[:10]]
    return discord.Embed(title="Achievement unlocked! ✨" if len(unlocked) == 1 else "Achievements unlocked! ✨",
                         description="\n".join(lines), color=discord.Color.gold())


async def notify(bot, guild_id, user_ids, channel):
    """Convenience hook for cogs: works even when the achievements service isn't loaded."""
    service = getattr(bot, "achievements", None)
    if service:
        await service.check(guild_id, user_ids, channel)
