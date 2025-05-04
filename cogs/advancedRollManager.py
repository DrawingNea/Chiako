import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
import math

class AdvancedRollManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def binomial_probability(self, dice_type: int, number_of_dices: int, actual_successes: int, success_threshold: int) -> float:
        """Calculate P(X ≥ k) for a binomial distribution."""
        n = number_of_dices  # number of trials (dices rolled)
        k = actual_successes
        p = (dice_type - success_threshold + 1) / dice_type
        prob = 0.0
        for i in range(k, n + 1):
            comb = math.comb(n, i)
            prob += comb * (p ** i) * ((1 - p) ** (n - i))
        return prob

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

    def get_embed_color_by_success_rate(self, successes: int, total: int) -> int:
        if total == 0:
            return 0x808080  # gray for no data

        ratio = successes / total

        gamma = 0.6
        curved_ratio = pow(ratio, gamma)

        # Interpolate between red (255, 0, 0) and green (0, 255, 0)
        red = int(255 * (1 - curved_ratio))
        green = int(255 * curved_ratio)
        blue = 0

        return (red << 16) + (green << 8) + blue

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
            probability = self.binomial_probability(diceType, number_of_dices, success_count, diceSuccess)
            filled_count = 10 - round(probability * 10)
            bar = "🟩" * filled_count + "⬜" * (10 - filled_count)
            color = self.get_embed_color_by_success_rate(success_count, number_of_dices)
            embed = discord.Embed(title=f"**Successful:** {success_count}\nProbability: {bar} - {probability:.2%}", description=message, color=color)

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            print(f"Error: {e}")
            await interaction.response.send_message(f"Could not roll the dice")

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
