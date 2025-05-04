import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks
import asyncio
import os
import re
import mysql.connector
from mysql.connector import Error
from discord.ext.commands import has_permissions, MissingPermissions


class VCManager(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @tasks.loop(seconds=10)
    async def waitforemptyvc(self, vcchannel: discord.VoiceChannel):
        return len(vcchannel.members)

"""
    @app_commands.command(name="openvc")
    async def createnewvoicechannel(self, ctx, name: str="Special Lounge", limit: int=5):
        await ctx.response.defer()
        server = ctx.guild
        v_channel = await server.create_voice_channel(ctx.user.name + "'s " + name, user_limit=limit)
        await ctx.followup.send("Created a new voice channel for you!")
        await asyncio.sleep(5)
        await vcusers = self.waitforemptyvc(v_channel)
        if vcusers == 0:
            self.waitforemptyvc.stop()
            v_channel.delete()
"""

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VCManager(bot))