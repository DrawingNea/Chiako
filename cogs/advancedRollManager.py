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

class AdvancedRollManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def extract_dice_values(self, result: d20.RollResult) -> List[int]:
        dice_values = []

        def recurse(term):
            if hasattr(term, "children"):  # composite term
                for child in term.children:
                    recurse(child)
            elif hasattr(term, "rolls"):  # Die node
                for roll in term.rolls:
                    if not roll.dropped:
                        dice_values.append(roll.value)

        recurse(result.expr)
        return dice_values

    def generate_dice_animation(self, result: d20.RollResult, roll_frames=10) -> io.BytesIO:
        dice_values = self.extract_dice_values(result)
        num_dice = len(dice_values)

        # Dimensions
        size = 100
        padding = 10
        width = max(size * num_dice + padding * 2, 500)
        height = size + 80

        try:
            font = ImageFont.truetype("arial.ttf", 36)
            font_big = ImageFont.truetype("arial.ttf", 48)
        except:
            font = ImageFont.load_default()
            font_big = ImageFont.load_default()

        frames = []

        for frame_index in range(roll_frames):
            image = Image.new("RGB", (width, height), (30, 30, 30))
            draw = ImageDraw.Draw(image)

            # Roll dice (random during animation, real on last frame)
            values = (
                [random.randint(1, 20) for _ in range(num_dice)]
                if frame_index < roll_frames - 1
                else dice_values
            )

            for i, val in enumerate(values):
                x = padding + i * size
                y = 10
                draw.rectangle(
                    [x, y, x + size - 10, y + size - 10],
                    fill=(200, 200, 200),
                    outline=(0, 0, 0)
                )

                # Center the number
                text = str(val)
                bbox = font.getbbox(text)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = x + (size - 10 - text_width) // 2
                text_y = y + (size - 10 - text_height) // 2
                draw.text((text_x, text_y), text, font=font, fill=(0, 0, 0))
            # Only show total on final frame
            if frame_index == roll_frames - 1:
                total_text = f"Total: {result.total}"
                bbox = font_big.getbbox(total_text)
                total_width = bbox[2] - bbox[0]
                draw.text(
                    ((width - total_width) // 2, size + 20),
                    total_text,
                    font=font_big,
                    fill=(255, 255, 255)
                )

            frames.append(image)

        # Save as animated GIF
        output = io.BytesIO()
        frames[0].save(
            output,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
            disposal=2
        )
        output.seek(0)
        return output


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
            result = d20.roll(expression)
            image_bytes = self.generate_dice_animation(result)
            file = discord.File(fp=image_bytes, filename="roll.gif")

            embed = discord.Embed(
                title="🎲 Rolling Dice...",
                description=f"`{expression}` ➜ **{result.total}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Details", value=f"`{result.result}`", inline=False)
            embed.set_image(url="attachment://roll.gif")

            await interaction.response.send_message(embed=embed, file=file)

        except d20.RollSyntaxError as e:
            await interaction.response.send_message(f"❌ Invalid dice expression: `{e}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
