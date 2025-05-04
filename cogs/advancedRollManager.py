import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random

class AdvancedRollManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_dice_rolls(self, diceType: int = 6, number_of_dices: int = 1, explosion: int = 6, success: int = 5) -> tuple:
        emoji_map = {
            0: "0️⃣", 1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
            6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"
        }
        roll_results = [[]]
        success_result = 0
        messageString = ""
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
                if(diceType > 10):
                    messageString += "[{}]".format(result_rolls[result_roll])
                else:
                    emoji = emoji_map.get(result_rolls[result_roll], f"[{result_rolls[result_roll]}]")
                    messageString += emoji
                if result_rolls[result_roll] >= success:
                    success_result += 1
        return roll_results, success_result, messageString

    @app_commands.command(name="roll", description="Roll some dice, like 2d20kh1 + 3")
    @app_commands.describe(
        number_of_dices="How many dices to roll",
        dice_type="Type of dice to roll (d6, d10, d20, etc.)",
    )
    async def roll(self,
        interaction: discord.Interaction,
        number_of_dices: int,
        dice_type:  Optional[int],
    ):
        # DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        sql = "SELECT DiceType, DiceExplosion, DiceSuccess FROM DiceSettings WHERE ServerId = {}".format(
            str(interaction.guild_id)
        )
        await cursor.execute(sql)
        record = await cursor.fetchone()
        if(dice_type is None):
            diceType = int(record[0])
        else:
            diceType = int(dice_type)
        diceExplosion = int(record[1])
        diceSuccess = int(record[2])
        try:
            roll_results, success_count, message = self.get_dice_rolls(diceType, number_of_dices, diceExplosion, diceSuccess)
            filled_count = round((success_count / number_of_dices) * 10)
            bar = "🟩" * filled_count + "⬜" * (10 - filled_count)
            embed = discord.Embed(title=f"**Successful:** {success_count}\nRate:{bar} - {round((success_count / number_of_dices)* 100)}%", description=message, color=0x00ff00)

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"Could not roll the dice")

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
