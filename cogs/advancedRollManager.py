import discord
from discord.ext import commands
from discord import app_commands
import d20
from PIL import Image, ImageDraw, ImageFont
import io
import re
from typing import Optional
from typing import List
import random
import pydice

class AdvancedRollManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_dice_rolls(self, diceType: int = 6, number_of_dices: int = 1, explosion: int = 6, success: int = 5) -> tuple:
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
                messageString += "[{}]".format(result_rolls[result_roll])
                if result_rolls[result_roll] >= success:
                    success_result += 1
        return roll_results, success_result, messageString

    # Image generation helpers
    def generate_dice_face(self, number: int, size=(100, 100)):
        img = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size[0], size[1]], outline="black", width=4)
        font = ImageFont.load_default()
        w, h = draw.textsize(str(number), font=font)
        draw.text(((size[0] - w) // 2, (size[1] - h) // 2), str(number), fill="black", font=font)
        return img

    def concatenate_faces(self, images):
        widths, heights = zip(*(img.size for img in images))
        total_width = sum(widths)
        max_height = max(heights)
        result = Image.new("RGB", (total_width, max_height), "white")
        x_offset = 0
        for im in images:
            result.paste(im, (x_offset, 0))
            x_offset += im.size[0]
        return result

    def generate_dice_roll_gif(self, roll_results, output_path="dice_roll.gif", duration=0.1):
        frames = []
        for result_group in roll_results:
            for _ in range(5):  # Flickering animation
                temp_rolls = [random.randint(1, 6) for _ in result_group]
                frame = self.concatenate_faces([self.generate_dice_face(r) for r in temp_rolls])
                frames.append(frame)
            final_frame = self.concatenate_faces([self.generate_dice_face(r) for r in result_group])
            frames.append(final_frame)

        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=int(duration * 1000),
            loop=0
        )
        return output_path

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
        expression = f"{number_of_dices}d{diceType}e{diceExplosion}k{diceSuccess}"
        try:
            roll_results, success_count, message = self.get_dice_rolls(dice, count, explode, success)
            gif_path = self.generate_dice_roll_gif(roll_results)

            file = discord.File(gif_path, filename="dice.gif")
            embed = discord.Embed(title=f"🎲 {success_count} successes", description=message, color=0x00ff00)
            embed.set_image(url="attachment://dice.gif")

            await interaction.response.send_message(embed=embed, file=file)
        except d20.RollSyntaxError as e:
            await interaction.response.send_message(f"❌ Invalid dice expression: `{e}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
