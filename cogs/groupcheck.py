"""/group-check: the GM asks everyone to roll the same thing; results are collected in one message."""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.db import Campaign
from core.helpers import COLOR_INFO, COLOR_SECRET, BaseView, load_env, require_campaign, require_gm
from core.achievements import notify
from core.rolls import build_roll, log_roll


class GroupCheckView(BaseView):
    def __init__(self, cog: "GroupCheck", campaign: Campaign, text: str, label: str, dc: Optional[int],
                 secret: bool):
        super().__init__(timeout=3600)
        self.cog, self.campaign, self.text, self.label, self.dc, self.secret = cog, campaign, text, label, dc, secret
        self.results: dict[int, dict] = {}
        self.closed = False
        if not secret:
            self.remove_item(self.gm_results)

    def _passed(self, r: dict) -> Optional[bool]:
        if r["success"] is not None:
            return r["success"]
        if self.dc is not None:
            return r["total"] >= self.dc
        return None

    def render(self, *, reveal: bool) -> discord.Embed:
        title = f"Group check: {self.label}" + (" · secret" if self.secret else "")
        intro = f"Everyone press **Roll**: rolls `{self.text}` for your active character."
        if self.dc is not None:
            intro += f" **DC {self.dc}**"
        if self.closed:
            intro = "Closed." + (f" DC {self.dc}" if self.dc is not None else "")

        rows = sorted(self.results.values(), key=lambda r: r["total"], reverse=True)
        lines = []
        for r in rows:
            if reveal:
                passed = self._passed(r)
                mark = "" if passed is None else ("" if passed else "")
                lines.append(f"**{r['name']}**: {r['summary']}{mark}")
            else:
                lines.append(f"**{r['name']}** rolled")
        body = "\n".join(lines) or "*No rolls yet.*"
        e = discord.Embed(title=title[:256], description=f"{intro}\n\n{body}",
                          color=COLOR_SECRET if self.secret else COLOR_INFO)

        if reveal and rows and (self.dc is not None or any(r["success"] is not None for r in rows)):
            passes = sum(1 for r in rows if self._passed(r))
            verdict = "The group succeeds" if passes * 2 >= len(rows) else "The group fails"
            e.set_footer(text=f"{passes}/{len(rows)} passed · {verdict} (half or more must pass)")
        elif rows:
            e.set_footer(text=f"{len(rows)} rolled")
        return e

    @discord.ui.button(label="Roll", emoji="🎲", style=discord.ButtonStyle.success)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.results:
            await interaction.response.send_message("You already rolled for this one.", ephemeral=True)
            return
        db = self.cog.db
        env = await load_env(db, self.campaign, interaction.user.id, interaction.guild_id)
        _, data = build_roll(env, interaction.user, self.text)
        name = env.character.name if env.character else interaction.user.display_name
        self.results[interaction.user.id] = dict(name=name, **data)
        await log_roll(db, data, guild_id=interaction.guild_id, channel_id=interaction.channel_id,
                       campaign=self.campaign, user_id=interaction.user.id, env=env, secret=self.secret)
        await interaction.response.edit_message(embed=self.render(reveal=not self.secret))
        if not self.secret:
            await notify(self.cog.bot, interaction.guild_id, [interaction.user.id], interaction.channel)
        if self.secret:
            await interaction.followup.send("Rolled! Only the GM sees the result.", ephemeral=True)

    @discord.ui.button(label="Results (GM)", style=discord.ButtonStyle.secondary)
    async def gm_results(self, interaction: discord.Interaction, button: discord.ui.Button):
        require_gm(interaction.user, self.campaign)
        await interaction.response.send_message(embed=self.render(reveal=True), ephemeral=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        require_gm(interaction.user, self.campaign)
        self.closed = True
        await interaction.response.edit_message(embed=self.render(reveal=not self.secret), view=None)
        self.stop()


class GroupCheck(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="group-check", description="Everyone rolls the same check (GM)")
    @app_commands.describe(roll="Skill, macro or dice, e.g. perception or 1d20+wis", label="What it's for",
                           dc="Optional difficulty to beat", secret="Only the GM sees the results")
    @app_commands.guild_only()
    async def group_check(self, interaction: discord.Interaction, roll: str, label: Optional[str] = None,
                          dc: Optional[int] = None, secret: bool = False):
        campaign = await require_campaign(self.db, interaction.channel)
        require_gm(interaction.user, campaign)
        roll = roll.strip()
        label = label or roll.replace("_", " ").title()
        view = GroupCheckView(self, campaign, roll, label, dc, secret)
        await interaction.response.send_message(embed=view.render(reveal=not secret), view=view)


async def setup(bot):
    await bot.add_cog(GroupCheck(bot))
