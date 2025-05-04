import discord
import random
from discord import app_commands
from discord.ext import commands
import re
from discord.ext.commands import has_permissions, MissingPermissions
from typing import Optional


class DiceRollManager(commands.Cog):

    client = discord.Client(intents=discord.Intents.default())

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dicesetup", description="Setup dice rolls")
    @has_permissions(administrator=True)
    @app_commands.rename(
        diceType="dicetype", diceExplosion="explosion", diceSuccess="success"
    )
    @app_commands.describe(
        diceType="Number of Dicetype (example d10 => 10)",
        diceExplosion="Double Roll on Dice Result Numbers",
        diceSuccess="Dice Result needed for a success",
    )
    async def createemb(self, ctx, diceType: int, diceExplosion: int, diceSuccess: int):
        await ctx.response.defer()
        # saving to DB the server id and message id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        try:
            sql = "INSERT INTO DiceSettings (ServerID, DiceType, DiceExplosion, DiceSuccess) VALUES ({0},{1},{2},{3}) ON DUPLICATE KEY UPDATE DiceType={1}, DiceExplosion={2}, DiceSuccess={3}".format(
                str(ctx.guild.id), diceType, diceExplosion, diceSuccess
            )
            print(sql)
            await cursor.execute(sql)
            cnx.commit()
        except Exception as ex:
            await ctx.followup.send("Dice-Settings could not be set for this server!")
            print(ex)
            return
        # Response Message for User Request
        await ctx.followup.send("Dice-Settings set for this server!")

    @createemb.error
    async def createemb_error(self, ctx, error):
        if isinstance(error, MissingPermissions):
            text = "Sorry {}, you do not have permissions to do that!".format(
                ctx.message.author
            )
            await self.bot.send_message(ctx.message.channel, text)

    def get_dice_rolls(self, diceType: int = 6, number_of_dices: int = 1, explosion: int = 6, success: int = 5) -> tuple:
        roll_results = [[]]
        success_result = 0
        for _ in range(number_of_dices):
            rollIndex = 0
            roll = random.randint(1, diceType)
            nested_list = roll_results[rollIndex]
            nested_list.append(roll)
            while roll >= explosion:
                rollIndex = rollIndex + 1
                roll = random.randint(1, diceType)
                if (len(roll_results) - 1) < rollIndex:
                    roll_results.append([roll])
                else:
                    nested_list = roll_results[rollIndex]
                    nested_list.append(roll)
        for index, result_rolls in enumerate(roll_results):
            if index != 0:
                messageString += "  - "
            result_rolls.sort(reverse=True)
            for result_roll in range(len(result_rolls)):
                if messageString != "":
                    messageString += " "
                messageString += "[{}]".format(result_rolls[result_roll])
                if result_rolls[result_roll] >= success:
                    success_result += 1
        return roll_results, success_result, messageString

    @commands.Cog.listener("on_message")
    async def diceroll(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            print(message.content)
            if (
                re.search(r"^roll\s?\d+|\sroll\s?\d+", message.content.lower())
                is not None
                or re.search(r"^würfel\s?\d+|\swürfel\s?\d+", message.content.lower())
                is not None
                or re.search(r"^w\d+\s|\sw\d+", message.content.lower()) is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[22:]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                diceNumbers = [
                    int(i) for i in re.findall(r"\d+", convertedMessage.lower())
                ]
                # DB
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                sql = "SELECT DiceType, DiceExplosion, DiceSuccess FROM DiceSettings WHERE ServerId = {}".format(
                    str(message.guild.id)
                )
                await cursor.execute(sql)
                record = await cursor.fetchone()
                diceRollNumbers = diceNumbers[0]
                diceType = int(record[0])
                diceExplosion = int(record[1])
                diceSuccess = int(record[2])
                messageString = "Results for " + message.author.mention + ":\n"
                result = self.get_dice_rolls(
                    diceType=diceType,
                    number_of_dices=diceRollNumbers,
                    explosion=diceExplosion,
                    success=diceSuccess,
                )
                messageString += result[2]
                success_result = result[1]
                roll_results = result[0]

                messageString += "\n**Successful: {}**".format(success_result)
                await message.channel.send(content=messageString, reference=message)

    @commands.hybrid_command(name='diceroll', with_app_command=True, description="Roll a dice")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.describe(
        number_of_dices="How many dices to roll",
        dice_type="Type of dice to roll (d6, d10, d20, etc.)",
    )
    async def dicerolls(self,
        ctx: commands.Context,
        number_of_dices: int,
        dice_type:  Optional[int],
    ):
        await ctx.response.defer()
        # DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        sql = "SELECT DiceType, DiceExplosion, DiceSuccess FROM DiceSettings WHERE ServerId = {}".format(
            str(ctx.guild.id)
        )
        await cursor.execute(sql)
        record = await cursor.fetchone()
        if(dice_type is None):
            diceType = int(record[0])
        else:
            diceType = int(dice_type)
        diceExplosion = int(record[1])
        diceSuccess = int(record[2])
        roll_results = [[]]
        messageString = "Results for " + ctx.author.mention + ":\n"
        success_result = 0
        for _ in range(number_of_dices):
            rollIndex = 0
            roll = random.randint(1, diceType)
            nested_list = roll_results[rollIndex]
            nested_list.append(roll)
            while roll >= diceExplosion:
                rollIndex = rollIndex + 1
                roll = random.randint(1, diceType)
                if (len(roll_results) - 1) < rollIndex:
                    roll_results.append([roll])
                else:
                    nested_list = roll_results[rollIndex]
                    nested_list.append(roll)
        for index, result_rolls in enumerate(roll_results):
            if index != 0:
                messageString += "  - "
            result_rolls.sort(reverse=True)
            for result_roll in range(len(result_rolls)):
                if messageString != "":
                    messageString += " "
                messageString += "[{}]".format(result_rolls[result_roll])
                if result_rolls[result_roll] >= diceSuccess:
                    success_result += 1
        messageString += "\n**Successful: {}**".format(success_result)
        await ctx.followup.send(messageString)

    @commands.Cog.listener("on_message")
    async def dicerollSkill(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            print(message.content)
            if (
                re.search(
                    r"roll\s?(auf|for)?\s(\w+\s?(&|und)\s?)+\w+",
                    message.content.lower(),
                )
                is not None
            ):
                if str(self.bot.user.id) in message.content:
                    convertedMessage = message.content[22:]
                else:
                    convertedMessage = message.content
                print(convertedMessage)
                skillsString = re.search(
                    r"roll\s?(auf|for)?\s((\w+\s?(&|und)\s?)+\w+)",
                    message.content.lower(),
                    re.IGNORECASE,
                ).group(2)
                skillsArray = re.split("&|und|,", skillsString)
                totalSkill = 0
                # DB
                cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
                cursor = await cnx.cursor()
                messageString = "Results for " + message.author.mention + ":\n"
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
                    totalSkill += currentSkillLevel
                    messageString += "\n{0}: {1}".format(skillName, currentSkillLevel)
                messageString += "\nTotal rolls: {0} \n\n".format(totalSkill)
                sql = "SELECT DiceType, DiceExplosion, DiceSuccess FROM DiceSettings WHERE ServerId = {}".format(
                    str(message.guild.id)
                )
                await cursor.execute(sql)
                record = await cursor.fetchone()
                diceType = int(record[0])
                diceExplosion = int(record[1])
                diceSuccess = int(record[2])
                roll_results = [[]]
                success_result = 0
                for _ in range(totalSkill):
                    rollIndex = 0
                    roll = random.randint(1, diceType)
                    nested_list = roll_results[rollIndex]
                    nested_list.append(roll)
                    while roll >= diceExplosion:
                        rollIndex = rollIndex + 1
                        roll = random.randint(1, diceType)
                        if (len(roll_results) - 1) < rollIndex:
                            roll_results.append([roll])
                        else:
                            nested_list = roll_results[rollIndex]
                            nested_list.append(roll)
                for index, result_rolls in enumerate(roll_results):
                    if index != 0:
                        messageString += "  - "
                    result_rolls.sort(reverse=True)
                    for result_roll in range(len(result_rolls)):
                        if messageString != "":
                            messageString += " "
                        messageString += "[{}]".format(result_rolls[result_roll])
                        if result_rolls[result_roll] >= diceSuccess:
                            success_result += 1
                messageString += "\n**Successful: {}**".format(success_result)
                await message.channel.send(content=messageString, reference=message)

    @commands.Cog.listener("on_message")
    async def thanks(self, message):
        if (
            str(self.bot.user.id) in message.content
            or self.bot.user.name.lower() in message.content.lower()
        ):
            if (
                "thanks" in message.content.lower()
                or "thank" in message.content.lower()
                or "danke" in message.content.lower()
            ):
                hearts = [
                    ":heart:",
                    ":yellow_heart:",
                    ":pink_heart:",
                    ":orange_heart:",
                    ":green_heart:",
                    ":light_blue_heart:",
                    ":blue_heart:",
                    ":purple_heart:",
                    ":white_heart:",
                    ":sparkling_heart:",
                    ":gift_heart:",
                ]
                await message.channel.send(content="You're welcome!", reference=message)
                await message.channel.send(
                    content=random.choice(hearts), reference=message
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DiceRollManager(bot))
