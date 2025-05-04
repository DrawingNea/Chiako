import discord
import random
from discord import app_commands
from discord.ext import commands
import os
import re
import mysql.connector
from mysql.connector import Error
from discord.ext.commands import has_permissions, MissingPermissions
import numpy as np
import random


class SkillManager(commands.Cog):

    client = discord.Client(intents=discord.Intents.default())

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="skillsetup", description="Setup skills")
    @app_commands.rename(
        skillName="skillname", currentSkillLevel="currentlevel", maxLevel="maxlevel"
    )
    @app_commands.describe(
        skillName="Name of the Skill",
        currentSkillLevel="Current Level of the Skill as a number",
        maxLevel="Maximum Level of the Skill as a number",
    )
    async def addSkill(
        self, ctx, skillName: str, currentSkillLevel: int = 1, maxLevel: int = 5
    ):
        await ctx.response.defer()
        userId = ctx.user.id
        # saving to DB the server id and message id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        try:
            sql = "INSERT INTO SkillTracker (UserID, SkillName, CurrentSkillLevel, MaxLevel) VALUES ('{0}','{1}',{2},{3}) ON DUPLICATE KEY UPDATE SkillName='{1}', CurrentSkillLevel={2}, MaxLevel={3}".format(
                str(userId), skillName, currentSkillLevel, maxLevel
            )
            print(sql)
            await cursor.execute(sql)
            cnx.commit()
        except Exception as ex:
            await ctx.followup.send("{0} could not been updated!".format(skillName))
            print(ex)
            return
        # Response Message for User Request
        await ctx.followup.send("{0} was updated!".format(skillName))

    @commands.Cog.listener("on_message")
    async def skillChanger(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            if (
                re.search(
                    r"(\w+)\s?(entspricht|=|equals)\s?(\d)(\svon|\/|\sof)\s?(\d)",
                    message.content.lower(),
                    re.IGNORECASE,
                )
                is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[self.bot.user.name.length :]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                skillMessage = re.search(
                    r"(\w+)\s?(entspricht|=|equals)\s?(\d)(\svon|\/|\sof)\s?(\d)",
                    message.content.lower(),
                    re.IGNORECASE,
                )
                skillName = skillMessage.group(1).capitalize()
                currentSkillLevel = int(skillMessage.group(3))
                maxLevel = int(skillMessage.group(5))
                userId = message.author.id
                # saving to DB the server id and message id
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                messageString = "{0} was updated!".format(skillName)
                try:
                    sql = "INSERT INTO SkillTracker (UserID, SkillName, CurrentSkillLevel, MaxLevel) VALUES ('{0}','{1}',{2},{3}) ON DUPLICATE KEY UPDATE SkillName='{1}', CurrentSkillLevel={2}, MaxLevel={3}".format(
                        str(userId), skillName, currentSkillLevel, maxLevel
                    )
                    print(sql)
                    await cursor.execute(sql)
                    cnx.commit()
                except Exception as ex:
                    messageString = "{0} could not been updated!".format(skillName)
                    print(ex)
                    return
                # Response Message for User Request
                await message.channel.send(content=messageString, reference=message)

    @commands.Cog.listener("on_message")
    async def skillOutput(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            if (
                re.search(
                    r"skill\s?(in|:|of)?\s(\w+)", message.content.lower(), re.IGNORECASE
                )
                is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[self.bot.user.name.length :]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                skillName = re.search(
                    r"skill\s?(in|:|of)?\s(\w+)",
                    convertedMessage.lower(),
                    re.IGNORECASE,
                ).group(2)
                # DB
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                sql = "SELECT SkillName, CurrentSkillLevel, MaxLevel FROM SkillTracker WHERE UserID = '{0}' AND SkillName = '{1}'".format(
                    str(message.author.id), skillName
                )
                await cursor.execute(sql)
                record = cursor.fetchone()
                skillName = str(record[0])
                currentSkillLevel = int(record[1])
                maxLevel = int(record[2])
                messageString = "Skill overview for " + message.author.mention + ":\n"
                messageString += "\n**{0}: {1}/{2}**".format(
                    skillName, currentSkillLevel, maxLevel
                )
                await message.channel.send(content=messageString, reference=message)

    @commands.Cog.listener("on_message")
    async def skillOutputAll(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            if (
                re.search(
                    r"(alle|all)\s?(meine|my)?\s?skills",
                    message.content.lower(),
                    re.IGNORECASE,
                )
                is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[self.bot.user.name.length :]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                # DB
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                sql = "SELECT SkillName, CurrentSkillLevel, MaxLevel FROM SkillTracker WHERE UserID = '{0}'".format(
                    str(message.author.id)
                )
                await cursor.execute(sql)
                records = await cursor.fetchall()
                messageString = "Skill overview for " + message.author.mention + ":\n"
                for record in records:
                    skillName = str(record[0])
                    currentSkillLevel = int(record[1])
                    maxLevel = int(record[2])
                    messageString += "\n**{0}: {1}/{2}**".format(
                        skillName, currentSkillLevel, maxLevel
                    )
                await message.channel.send(content=messageString, reference=message)

    @commands.Cog.listener("on_message")
    async def skillOutputCalculated(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            if (
                re.search(
                    r"(berechne|calculate)\s?(meine|my)?\s?skill(s)?\s?(für|fuer|for)?\s?(\w+\s?(&|und)\s?)+\w+",
                    message.content.lower(),
                    re.IGNORECASE,
                )
                is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[self.bot.user.name.length :]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                skillsString = re.search(
                    r"skill(s)?\s?(für|fuer|for)?\s?((\w+\s?(&|und|,)\s?)+\w+)",
                    message.content.lower(),
                    re.IGNORECASE,
                ).group(3)
                skillsArray = re.split("&|und|,", skillsString)
                messageString = (
                    "Skills calculated for " + message.author.mention + ":\n"
                )
                totalLevel = 0
                # DB
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                for skill in skillsArray:
                    skill = skill.strip()
                    sql = "SELECT SkillName, CurrentSkillLevel FROM SkillTracker WHERE UserID = '{0}' AND SkillName = '{1}'".format(
                        str(message.author.id), skill
                    )
                    await cursor.execute(sql)
                    record = await cursor.fetchone()
                    if record is None:
                        continue
                    skillName = str(record[0])
                    currentSkillLevel = int(record[1])
                    totalLevel += currentSkillLevel
                    messageString += "\n{0}: {1}".format(skillName, currentSkillLevel)
                messageString += "\n\n**{0}: {1}**".format("Total", totalLevel)
                await message.channel.send(content=messageString, reference=message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SkillManager(bot))
