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

    # Function to generate dice face images for any number of faces (1–n)
    def generate_dice_face(number, sides):
        size = (100, 100)  # Size of the dice face
        img = Image.new("RGB", size, "white")  # Create a white background
        draw = ImageDraw.Draw(img)

        # Draw the outline of the die
        draw.rectangle([0, 0, size[0], size[1]], outline="black", width=5)

        # For a d20, we'll use numbers instead of dots
        font = ImageFont.load_default()
        text = str(number)

        # Get text size to center it
        text_width, text_height = draw.textsize(text, font=font)
        position = ((size[0] - text_width) // 2, (size[1] - text_height) // 2)
        draw.text(position, text, fill="black", font=font)

        return img

    # Generate an animated roll for any die type (d6, d12, d20, etc.)
    def generate_dice_roll_gif(sides, rolls, output_path="dice_roll.gif", duration=0.1):
        frames = []
        
        # Generate a smooth rolling effect by changing faces randomly
        for _ in range(15):  # Create 15 frames for smooth animation
            rand_num = random.randint(1, sides)  # Random face between 1 and 'sides'
            frame = generate_dice_face(rand_num, sides)
            frames.append(frame)
        
        # Add the actual roll results
        for roll in rolls:
            frame = generate_dice_face(roll, sides)
            frames.append(frame)

        # Save the animation as a GIF
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=int(duration * 1000),  # Duration in milliseconds per frame
            loop=0
        )

        return output_path, rolls



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
            dice_roll = d20.roll(expression)
            roll_results = dice_roll.results
            sides = roll_results[0].sides if roll_results else 6
            rolls = [r.result for r in roll_results]
            gif_path, final_rolls = self.generate_dice_roll_gif(sides, rolls)
            file = discord.File(gif_path, filename="dice.gif")
            embed = discord.Embed(title=f"Roll Result: {', '.join(map(str, final_rolls))}", color=0x00ff00)
            embed.set_image(url="attachment://dice.gif")
            
            await interaction.response.send_message(embed=embed, file=file)
        except d20.RollSyntaxError as e:
            await interaction.response.send_message(f"❌ Invalid dice expression: `{e}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdvancedRollManager(bot))
