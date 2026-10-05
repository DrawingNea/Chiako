"""Sessions & recaps (/session), dice statistics (/stats), /halloffame and /achievements."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core import clock
from core.achievements import ACHIEVEMENTS, notify
from core.helpers import COLOR_INFO, UserError, get_campaign, require_campaign, require_gm
from core.recap import duration, medal, recap_embed
from core.stats import (
    MIN_DICE_FOR_LUCK, by_user, describe_setting, die_order, distribution, leaderboard, luck_verdict, pct,
    pool_verdict, summarize,
)

SCOPES = [Choice(name="This session", value="session"), Choice(name="This campaign", value="campaign"),
          Choice(name="Whole server", value="server")]


class Sessions(commands.Cog):
    session = app_commands.Group(name="session", description="Game sessions and recaps", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    # ------------------------------------------------------------------ /session

    @session.command(name="start", description="Start a game session (GM). Everything until /session end goes in the recap")
    @app_commands.describe(title="Optional title, e.g. 'The Goblin Cave'")
    async def start(self, interaction: discord.Interaction, title: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        if await self.db.get_active_session(campaign.id):
            raise UserError("A session is already running. End it with `/session end`.")
        s = await self.db.start_session(campaign.id, interaction.channel.id, (title or "").strip()[:100] or None)
        sched = await self.db.get_schedule(campaign.id)
        if sched and abs(sched.starts_at - clock.now()) <= 6 * 3600:
            await self.db.delete_schedule(campaign.id)  # this is the scheduled session, no more reminders
        await interaction.response.send_message(
            f"**Session {s.number}** begins" + (f": *{s.title}*" if s.title else "") + "! 🎲\n"
            "-# Mark memorable moments with `/session moment`. The GM ends it with `/session end` for a recap.")

    @session.command(name="end", description="End the session and post the recap (GM)")
    async def end(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        active = await self.db.get_active_session(campaign.id)
        if not active:
            raise UserError("No session is running. Start one with `/session start`.")
        s = await self.db.end_session(active.id)
        await interaction.response.send_message(embed=await recap_embed(self.db, campaign, s),
                                                allowed_mentions=discord.AllowedMentions.none())
        rows = await self.db.roll_rows(guild_id=interaction.guild_id, campaign_id=campaign.id,
                                       start=s.started_at, end=s.ended_at)
        await notify(self.bot, interaction.guild_id, {r.user_id for r in rows}, interaction.channel)

    @session.command(name="moment", description="Remember a moment for the recap")
    @app_commands.describe(text="e.g. 'Grom tried to seduce the dragon'")
    async def moment(self, interaction: discord.Interaction, text: str):
        campaign = await require_campaign(self.db, interaction.channel)
        ch = await self.db.get_active_character(campaign.id, interaction.user.id)
        who = ch.name if ch else interaction.user.display_name
        text = " ".join(text.split())[:250]
        await self.db.add_event(campaign_id=campaign.id, guild_id=interaction.guild_id, kind="moment",
                                text=f"{text} ({who})", user_id=interaction.user.id)
        running = await self.db.get_active_session(campaign.id)
        note = "" if running else "\n-# No session is running, so this won't be in a recap."
        await interaction.response.send_message(f"Noted: *{text}*{note}")

    @session.command(name="recap", description="Show the recap of a session")
    @app_commands.describe(number="Session number (default: the latest)", public="Post it for everyone")
    async def recap(self, interaction: discord.Interaction, number: Optional[int] = None, public: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        s = await self.db.get_session(campaign.id, number)
        if not s:
            raise UserError("No sessions yet." if number is None else f"There's no session {number}.")
        await interaction.response.send_message(embed=await recap_embed(self.db, campaign, s), ephemeral=not public,
                                                allowed_mentions=discord.AllowedMentions.none())

    @session.command(name="list", description="All sessions of this campaign")
    async def list_cmd(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        sessions = await self.db.list_sessions(campaign.id)
        if not sessions:
            raise UserError("No sessions yet. The GM starts one with `/session start`.")
        lines = []
        for s in sessions:
            length = duration((s.ended_at or clock.now()) - s.started_at)
            lines.append(f"**{s.number}.** {s.title or '*untitled*'} · <t:{s.started_at}:d> · {length}"
                         + ("" if s.ended_at else " · running"))
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    # ------------------------------------------------------------------ scope helper

    async def _rows(self, interaction, scope: str, user_id: Optional[int] = None):
        campaign = await get_campaign(self.db, interaction.channel)
        if scope == "server":
            return await self.db.roll_rows(guild_id=interaction.guild_id, user_id=user_id), "this server", campaign
        if not campaign:
            raise UserError("This channel isn't part of a campaign. Use `scope: Whole server`.")
        if scope == "session":
            s = await self.db.get_active_session(campaign.id) or await self.db.get_session(campaign.id)
            if not s:
                raise UserError("No sessions yet.")
            rows = await self.db.roll_rows(guild_id=interaction.guild_id, user_id=user_id, campaign_id=campaign.id,
                                           start=s.started_at, end=s.ended_at or clock.now())
            return rows, f"session {s.number}", campaign
        rows = await self.db.roll_rows(guild_id=interaction.guild_id, user_id=user_id, campaign_id=campaign.id)
        return rows, campaign.name, campaign

    async def _default_scope(self, interaction) -> str:
        return "campaign" if await get_campaign(self.db, interaction.channel) else "server"

    # ------------------------------------------------------------------ /stats

    @app_commands.command(name="stats", description="Dice statistics: luck, success pools, every die type")
    @app_commands.describe(player="Whose stats (default: yours)", scope="Which rolls count", public="Post it for everyone")
    @app_commands.choices(scope=SCOPES)
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction, player: Optional[discord.Member] = None,
                    scope: Optional[Choice[str]] = None, public: bool = False):
        who = player or interaction.user
        scope_value = scope.value if scope else await self._default_scope(interaction)
        rows, where, _ = await self._rows(interaction, scope_value, who.id)
        s = summarize(rows)
        e = discord.Embed(title=f"{who.display_name}'s dice · {where}", color=COLOR_INFO)
        if not s.rolls:
            e.description = "No public rolls yet. Secret rolls never count."
            await interaction.response.send_message(embed=e, ephemeral=not public)
            return

        e.description = (f"**{s.rolls}** roll{'s' if s.rolls != 1 else ''} · "
                         f"**{s.dice}** {'die' if s.dice == 1 else 'dice'}\n"
                         f"### {luck_verdict(s)}")

        # Success pools, one section per set of rules
        for setting, ps in sorted(s.pools.items(), key=lambda kv: -kv[1].rolls)[:4]:
            lines = [f"{ps.rolls} roll{'s' if ps.rolls != 1 else ''} · **{ps.successes}** successes · "
                     f"Ø **{ps.average:.1f}** per roll"]
            if ps.expected_rolls:
                exp = ps.expected / ps.expected_rolls
                actual = ps.expected_successes / ps.expected_rolls
                lines.append(f"{actual:.1f} per roll vs. {exp:.1f} expected ({pool_verdict(ps)})")
            lines.append(f"{ps.zero} without a success ({pct(ps.zero, ps.rolls)}) · best {ps.best}")
            if ps.bonus_dice:
                lines.append(f"{ps.bonus_dice} bonus dice from explosions")
            e.add_field(name=f"{describe_setting(setting)}", value="\n".join(lines), inline=False)

        # Every die type: average and how often the top and bottom faces came up
        for sides in die_order(s.faces)[:4]:
            values = s.faces[sides]
            if sides == "F":
                plus, minus = values.count(1), values.count(-1)
                e.add_field(name=f"Fate dice · {len(values)}", inline=False, value=(
                    f"plus: {plus} ({pct(plus, len(values))}) · minus: {minus} ({pct(minus, len(values))})"
                    f" · expected 33.3% each"))
                continue
            n = int(sides)
            top, bottom = values.count(n), values.count(1)
            e.add_field(name=f"d{n} · {len(values)} {'die' if len(values) == 1 else 'dice'}", inline=False, value=(
                f"Ø **{sum(values) / len(values):.2f}** · expected {(n + 1) / 2:g}\n"
                f"{n}s: {top}× ({pct(top, len(values))}) · 1s: {bottom}× "
                f"({pct(bottom, len(values))}) · expected {100 / n:.1f}% each"))

        if s.checks:
            e.add_field(name="3d20 checks", inline=False,
                        value=f"{s.checks} checks · {s.checks_passed} passed ({pct(s.checks_passed, s.checks)})")
        if s.best:
            e.add_field(name="Biggest total", inline=False,
                        value=f"**{s.best.total}**" + (f" · {s.best.label}" if s.best.label else ""))

        # Chart of the most-rolled die type
        chart = next((k for k in die_order(s.faces) if k != "F" and 2 <= int(k) <= 20), None)
        if chart:
            e.add_field(name=f"d{chart} results", inline=False,
                        value=f"```\n{distribution(s.faces[chart], int(chart))}\n```")
        e.set_footer(text="Secret rolls are never counted.")
        await interaction.response.send_message(embed=e, ephemeral=not public)

    # ------------------------------------------------------------------ /halloffame

    @app_commands.command(name="halloffame", description="Leaderboards: crits, fumbles, luck, biggest rolls, slayers")
    @app_commands.choices(scope=[c for c in SCOPES if c.value != "session"])
    @app_commands.guild_only()
    async def halloffame(self, interaction: discord.Interaction, scope: Optional[Choice[str]] = None):
        scope_value = scope.value if scope else await self._default_scope(interaction)
        rows, where, campaign = await self._rows(interaction, scope_value)
        users = by_user(rows)
        e = discord.Embed(title=f"Hall of Fame · {where}", color=discord.Color.gold())

        def board(items, fmt) -> str:
            return "\n".join(f"{medal(i)} <@{uid}> {fmt(v)}" for i, (uid, v) in enumerate(items)) or "—"

        lucky = lambda s: s.dice >= MIN_DICE_FOR_LUCK and s.luck > 0  # noqa: E731
        unlucky = lambda s: s.dice >= MIN_DICE_FOR_LUCK and s.luck < 0  # noqa: E731
        e.add_field(name="Most natural 20s", value=board(
            leaderboard(users, lambda s: s.nat20 or None), lambda v: f"· {v}"))
        e.add_field(name="Most natural 1s", value=board(
            leaderboard(users, lambda s: s.nat1 or None), lambda v: f"· {v}"))
        e.add_field(name="\u200b", value="\u200b")
        e.add_field(name="Luckiest", value=board(
            leaderboard(users, lambda s: s.luck, minimum=lucky), lambda v: f"· {v:+.1f}%"))
        e.add_field(name="Unluckiest", value=board(
            leaderboard(users, lambda s: s.luck, minimum=unlucky, reverse=False), lambda v: f"· {v:+.1f}%"))
        e.add_field(name="\u200b", value="\u200b")
        best = sorted((s.best for s in users.values() if s.best), key=lambda r: -r.total)[:3]
        e.add_field(name="Biggest rolls", inline=False, value="\n".join(
            f"{medal(i)} <@{r.user_id}> · **{r.total}**" + (f" ({r.label})" if r.label else "")
            for i, r in enumerate(best)) or "—")
        slayers = await self.db.events_by_user(interaction.guild_id, "defeat",
                                               campaign.id if scope_value == "campaign" and campaign else None)
        e.add_field(name="Monster slayers", value=board(slayers, lambda v: f"· {v}"))
        e.add_field(name="Achievements", value=board(
            (await self.db.achievement_counts(interaction.guild_id))[:3], lambda v: f"· {v}/{len(ACHIEVEMENTS)}"))
        e.set_footer(text=f"Luck = how far above or below average all your dice land (needs {MIN_DICE_FOR_LUCK}+ "
                          f"dice). Secret rolls never count.")
        await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------------ /achievements

    @app_commands.command(name="achievements", description="Unlocked and locked achievements")
    @app_commands.guild_only()
    async def achievements(self, interaction: discord.Interaction, player: Optional[discord.Member] = None):
        who = player or interaction.user
        have = await self.db.unlocked_achievements(interaction.guild_id, who.id)
        lines = []
        for a in ACHIEVEMENTS:
            if a.key in have:
                lines.append(f"✓ **{a.name}**: {a.description} · <t:{have[a.key]}:d>")
            else:
                lines.append(f"-# {a.name}: {a.description}")
        e = discord.Embed(title=f"{who.display_name} · {len(have)}/{len(ACHIEVEMENTS)}",
                          description="\n".join(lines)[:4000], color=discord.Color.gold())
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Sessions(bot))
