"""Scheduling: the next session's date and automatic reminders (the day before, an hour before, at the start)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import clock
from core.db import Campaign
from core.helpers import UserError, require_campaign, require_gm
from core.i18n import t
from core.scheduling import fmt, get_zone, parse_when

log = logging.getLogger("dicebot")
PINGS = discord.AllowedMentions(users=True, roles=True, everyone=False)
DAY, HOUR = 86400, 3600
# Bits in scheduled_sessions.reminded
DAY_BEFORE, HOUR_BEFORE, START = 1, 2, 4


def day_word(ts: int, now: int, tz_name: str) -> str:
    """'today', 'tomorrow' or the weekday of ts ('Friday'), by the calendar in the campaign's time zone."""
    tz = get_zone(tz_name)
    days = (datetime.fromtimestamp(ts, tz).date() - datetime.fromtimestamp(now, tz).date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return datetime.fromtimestamp(ts, tz).strftime("%A")


def day_headline(day: str, lang: str) -> str:
    if day == "tomorrow":
        return t(lang, "Tomorrow is session day!")
    if day == "today":
        return t(lang, "Session today!")
    return t(lang, "Session {day}!", day=t(lang, "on {weekday}", weekday=t(lang, day)))


class Scheduling(commands.Cog):
    schedule = app_commands.Group(name="schedule", description="Plan the next session", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        if hasattr(self.bot, "wait_until_ready"):  # real bot only; tests call check_reminders directly
            self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    # ------------------------------------------------------------------ helpers

    async def _ping_line(self, campaign: Campaign) -> str:
        ids = [campaign.gm_user_id] + [u for u in await self.db.campaign_player_ids(campaign.id)
                                       if u != campaign.gm_user_id]
        line = " ".join(f"<@{u}>" for u in ids)
        if campaign.gm_role_id:
            line += f" <@&{campaign.gm_role_id}>"
        return line

    async def _channel(self, channel_id: int):
        ch = self.bot.get_channel(channel_id)
        if ch is None:
            try:
                ch = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return None
        return ch

    # ------------------------------------------------------------------ commands

    @schedule.command(name="set", description="Set the next session (GM). Everyone is reminded the day before")
    @app_commands.describe(when="e.g. 'fri 19:30', 'tomorrow 19:30', '9.10. 19:30' or '2026-10-09 19:30'",
                           title="Optional title")
    async def set_cmd(self, interaction: discord.Interaction, when: str, title: Optional[str] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        now = clock.now()
        ts = parse_when(when, campaign.timezone, now)
        await self.db.set_schedule(campaign.id, interaction.channel.id, ts, (title or "").strip()[:100] or None)
        lang = campaign.language
        if ts - now <= DAY:
            # Less than a day away: this announcement is the day-before reminder
            await self.db.mark_reminded(campaign.id, DAY_BEFORE)
            reminders = t(lang, "I'll remind everyone an hour before.")
        else:
            reminders = t(lang, "I'll remind everyone the day before and an hour before.")
        await interaction.response.send_message(
            t(lang, "Next session") + (f" **{title.strip()}**" if title else "") + f": {fmt(ts)}\n"
            f"{reminders} {await self._ping_line(campaign)}",
            allowed_mentions=PINGS)

    @schedule.command(name="show", description="When is the next session?")
    async def show(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        s = await self.db.get_schedule(campaign.id)
        if not s:
            raise UserError("No session is scheduled. The GM sets one with `/schedule set`.")
        await interaction.response.send_message(
            t(campaign.language, "Next session") + (f" **{s.title}**" if s.title else "") + f": {fmt(s.starts_at)}",
            ephemeral=True)

    @schedule.command(name="cancel", description="Cancel the scheduled session (GM)")
    async def cancel(self, interaction: discord.Interaction):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        s = await self.db.get_schedule(campaign.id)
        if not s or not await self.db.delete_schedule(campaign.id):
            raise UserError("No session is scheduled.")
        await interaction.response.send_message(
            t(campaign.language, "The session on {when} is cancelled.", when=f"<t:{s.starts_at}:F>")
            + f" {await self._ping_line(campaign)}",
            allowed_mentions=PINGS)

    # ------------------------------------------------------------------ reminders

    async def check_reminders(self, now: Optional[int] = None) -> int:
        """Send due reminders. Returns how many were sent. Called every minute by the loop."""
        now = clock.now() if now is None else now
        sent = 0
        for s in await self.db.all_schedules():
            left = s.starts_at - now
            if left < -HOUR:                      # long past (bot was offline): clean up quietly
                await self.db.delete_schedule(s.campaign_id)
                continue
            campaign = await self.db.get_campaign(s.campaign_id)
            lang = campaign.language if campaign else "en"
            name = f"**{s.title}**" if s.title else t(lang, "The session")
            if left <= 0 and not s.reminded & START:
                text = t(lang, "**Game time!** {name} starts now!", name=name) + " 🎲"
                bits = DAY_BEFORE | HOUR_BEFORE | START
            elif 0 < left <= HOUR and not s.reminded & HOUR_BEFORE:
                text = t(lang, "{name} starts {when}!", name=name, when=f"<t:{s.starts_at}:R>")
                bits = DAY_BEFORE | HOUR_BEFORE
            elif HOUR < left <= DAY and not s.reminded & DAY_BEFORE:
                day = day_word(s.starts_at, now, campaign.timezone if campaign else "UTC")
                text = t(lang, "**{headline}** {name} starts {when}.", headline=day_headline(day, lang), name=name,
                         when=fmt(s.starts_at)) + " 🌸"
                bits = DAY_BEFORE
            else:
                continue
            channel = await self._channel(s.channel_id)
            if channel and campaign:
                try:
                    await channel.send(f"{text} {await self._ping_line(campaign)}", allowed_mentions=PINGS)
                    sent += 1
                except discord.HTTPException as e:
                    log.warning("Reminder failed: %s", e)
            if bits & START:
                await self.db.delete_schedule(s.campaign_id)
            else:
                await self.db.mark_reminded(s.campaign_id, bits)
        return sent

    @tasks.loop(seconds=60)
    async def reminder_loop(self):
        try:
            await self.check_reminders()
        except Exception:
            log.exception("Reminder loop failed")

    @reminder_loop.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scheduling(bot))
