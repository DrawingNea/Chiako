import discord
from discord.ext import commands
from discord import app_commands
import d20
from PIL import Image, ImageDraw, ImageFont
import io
import re
from typing import Optional
from typing import List

class AdvancedRollManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def extract_dice_values(self, result: d20.RollResult) -> List[int]:
        return [r.value for r in result.rolls if not r.dropped]

    def generate_dice_image(self, result: d20.RollResult) -> io.BytesIO:
      dice_values = self.extract_dice_values(result)

      size = 100
      padding = 10
      width = max(size * len(dice_values) + padding * 2, 500)
      height = size + 60

      image = Image.new("RGB", (width, height), (30, 30, 30))
      draw = ImageDraw.Draw(image)

      try:
          try:
              font = ImageFont.truetype("arial.ttf", 36)
              font_big = ImageFont.truetype("arial.ttf", 48)
          except OSError:
              font = ImageFont.truetype("path/to/fallback_font.ttf", 36)
              font_big = ImageFont.truetype("path/to/fallback_font.ttf", 48)
      except:
          font = ImageFont.load_default()
          font_big = ImageFont.load_default()

      for i, val in enumerate(dice_values):
          x = padding + i * size
          y = 10
          draw.rectangle([x, y, x + size - 10, y + size - 10], fill=(200, 200, 200), outline=(0, 0, 0))
          draw.text((x + 25, y + 25), str(val), font=font, fill=(0, 0, 0))

      draw.text((padding, size + 20), f"Total: {result.total}", font=font_big, fill=(255, 255, 255))

      output = io.BytesIO()
      image.save(output, format='PNG')
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
            image_bytes = self.generate_dice_image(result)
            file = discord.File(fp=image_bytes, filename="roll.png")

            embed = discord.Embed(
                title="🎲 Dice Roll",
                description=f"`{expression}` ➜ **{result.total}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Details", value=f"`{result.result}`", inline=False)
            embed.set_image(url="attachment://roll.png")

            await interaction.response.send_message(embed=embed, file=file)

        except d20.RollSyntaxError as e:
            await interaction.response.send_message(f"❌ Invalid dice expression: `{e}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
