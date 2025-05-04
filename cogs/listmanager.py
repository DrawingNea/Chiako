import discord
from discord import app_commands
from discord.ext import commands
import os
import re
import mysql.connector
from mysql.connector import Error
from discord.ext.commands import has_permissions, MissingPermissions


class Listmanager(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="listsetup", description="Setup the Embed Message")
    @has_permissions(administrator=True)
    @app_commands.rename(title="embed-title",
                         description="description-text",
                         imglink="link-of-image"
                         )
    @app_commands.describe(title="Title of your embed message",
                           description="Description of your embed message",
                           imglink="A link to an image to show in your embed message")
    async def createemb(self, ctx, title: str, description: str, imglink: str,
                        footer: str):
        await ctx.response.defer()
        # creating embed object and setting content
        embedMsg = discord.Embed(title=title,
                                 description=description,
                                 colour=discord.Colour.purple())
        embedMsg.set_image(url=imglink)
        embedMsg.set_footer(text=footer)
        # send new created embed to current channel
        msg = await ctx.channel.send(embed=embedMsg)
        # saving to DB the server id and message id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("INSERT INTO EmbedList (ServerID, ChannelID, MessageID) VALUES (%s, %s, %s)" % str(ctx.guild.id),
                       ctx.channel.id, msg.id)
        # Response Message for User Request
        await ctx.followup.send("Created Embedmessage!")

    @createemb.error
    async def createemb_error(self, ctx, error):
        if isinstance(error, MissingPermissions):
            text = "Sorry {}, you do not have permissions to do that!".format(ctx.message.author)
            await self.bot.send_message(ctx.message.channel, text)

    @app_commands.rename(itemname="itemname")
    @app_commands.describe(itemname="Name of your item which will be added")
    @app_commands.command(name="additem", description="Add an item to your list")
    async def additem(self, ctx, itemname: str):
        await ctx.response.defer()
        # Get Message ID of Embed from DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT MESSAGEID FROM EmbedList WHERE ServerId = %s" % (str(ctx.guild.id)))
        record = await cursor.fetchone()
        msgid = record[0]
        # Search for Message in current Channel
        testmsg = await ctx.channel.fetch_message(msgid)
        # Loop through all embeds in Message
        for emb in testmsg.embeds:
            # Test if embed message has no fields yet
            if (len(emb.fields) == 0):
                # Add first field to embed
                emb.add_field(name=ctx.user.name, value=itemname, inline=False)
                await testmsg.edit(embed=emb)
                # Response Message for User Request
                await ctx.followup.send(itemname + " has been added to the list!", ephemeral=True)
                # Append changes to embed message
                return await testmsg.edit(embed=emb)
            # Loop through all fields in Embed
            for idx, field in enumerate(emb.fields):
                # Test if Field belongs to User
                if (field.name == ctx.user.name):
                    # Add new Item to the fields Value
                    emb.set_field_at(index=idx,
                                     name=ctx.user.name,
                                     value=field.value + "\n" + itemname,
                                     inline=False)
                    # Response Message for User Request
                    await ctx.followup.send(itemname + " has been added to the list!", ephemeral=True)
                    # Append changes to embed message
                    return await testmsg.edit(embed=emb)
        # Create a new field for user if there is no existing field from user
        testmsg.embeds[0].add_field(name=ctx.user.name, value=itemname, inline=False)
        # Response Message for User Request
        await ctx.followup.send(itemname + " has been added to the list!", ephemeral=True)
        # Append changes to embed message
        return await testmsg.edit(embed=testmsg.embeds[0])

    @app_commands.rename(itemname="itemname")
    @app_commands.describe(itemname="Name of your item which will be removed")
    @app_commands.command(name="removeitem",
                          description="Remove an item from your list")
    async def removeitem(self, ctx, itemname: str):
        await ctx.response.defer()
        # Get message id by server id from DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT MESSAGEID FROM EmbedList WHERE ServerId = %s" % (str(ctx.guild.id)))
        record = await cursor.fetchone()
        msgid = record[0]
        # Fetch message from discord channel
        testmsg = await ctx.channel.fetch_message(msgid)
        # Loop through all embeds in Message
        for emb in testmsg.embeds:
            # Loop through all fields in Embed
            for idx, field in enumerate(emb.fields):
                # Test if Field belongs to User
                if (field.name == ctx.user.name):
                    # Test if item is in Field Value
                    if (re.search("^" + itemname + "$\n?", field.value, flags=re.MULTILINE | re.IGNORECASE)):
                        # Test if item is not the only Value of Field
                        if (len(field.value.replace(itemname, "")) > 0):
                            # Remove Item from Value of Field
                            emb.set_field_at(index=idx, name=ctx.user.name,
                                             value=re.sub("^" + itemname + "$\n?", "", field.value,
                                                          flags=re.MULTILINE | re.IGNORECASE))
                            # Response Message for User Request
                            await ctx.followup.send(itemname + " has been removed!", ephemeral=True)
                            # Append changes to embed message
                            return await testmsg.edit(embed=emb)
                        # If Field has only Item as Value
                        else:
                            # Remove entire Field from Embed
                            emb.remove_field(idx)
                            # Response Message for User Request
                            await ctx.followup.send(itemname + " has been removed!", ephemeral=True)
                            # Append changes to embed message
                            return await testmsg.edit(embed=emb)
        # Response Message for User Request
        await ctx.followup.send(itemname + " not found!", ephemeral=True)

    @app_commands.rename(itemname="itemname")
    @app_commands.describe(itemname="Name of your item which you are looking for")
    @app_commands.command(name="whohasitem",
                          description="Search for the user that has named item")
    async def whohasitem(self, ctx, itemname: str):
        await ctx.response.defer()
        # Get message id by server id from DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT MESSAGEID FROM EmbedList WHERE ServerId = %s" % (str(ctx.guild.id)))
        record = await cursor.fetchone()
        msgid = record[0]
        # Fetch message from discord channel
        testmsg = await ctx.channel.fetch_message(msgid)
        # Loop through all embeds in Message
        for emb in testmsg.embeds:
            # Loop through all fields in Embed
            for idx, field in enumerate(emb.fields):
                # Test if item is in Field Value
                if (itemname in field.value):
                    # Response Message for User Request
                    await ctx.followup.send(field.name + " has " + itemname, ephemeral=True)
                    return
        # Response Message for User Request
        await ctx.followup.send("No one has " + itemname, ephemeral=True)

    @app_commands.rename(messageid="message-id")
    @app_commands.describe(messageid="Message ID to change your list too")
    @app_commands.command(name="changemsgid",
                          description="Change the utilized embedmessage")
    @has_permissions(administrator=True)
    async def changemsgid(self, ctx, messageid: str):
        await ctx.response.defer()
        # saving to DB the server id and message id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("UPDATE EmbedList SET MessageID = %s WHERE ServerID = %s" % messageid, str(ctx.guild.id))
        cnx.commit()
        # Response Message for User Request
        await ctx.followup.send("Embedmessage linked!", ephemeral=True)

    @changemsgid.error
    async def changemsgid_error(self, ctx, error):
        if isinstance(error, MissingPermissions):
            text = "Sorry {}, you do not have permissions to do that!".format(ctx.message.author)
            await self.bot.send_message(ctx.message.channel, text)

    @app_commands.rename(itemname="itemname",
                         user="member")
    @app_commands.describe(itemname="Message ID to change your list too",
                           user="Member from which item should be removed")
    @app_commands.command(name="removeitemfromuser",
                          description="Remove an item from an users list")
    @has_permissions(administrator=True)
    async def removeitemfromuser(self, ctx, itemname: str, user: discord.Member):
        await ctx.response.defer()
        # Get message id by server id from DB
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT MESSAGEID FROM EmbedList WHERE ServerId = %s" % (str(ctx.guild.id)))
        record = await cursor.fetchone()
        msgid = record[0]
        # Fetch message from discord channel
        testmsg = await ctx.channel.fetch_message(msgid)
        # Loop through all embeds in Message
        for emb in testmsg.embeds:
            # Loop through all fields in Embed
            for idx, field in enumerate(emb.fields):
                # Test if Field belongs to User
                if (field.name == user.name):
                    # Test if item is in Field Value
                    if (re.search("^" + itemname + "$\n?", field.value, flags=re.MULTILINE | re.IGNORECASE)):
                        # Test if item is not the only Value of Field
                        if (len(field.value.replace(itemname, "")) > 0):
                            # Remove Item from Value of Field
                            emb.set_field_at(index=idx, name=ctx.user.name,
                                             value=re.sub("^" + itemname + "$\n?", "", field.value,
                                                          flags=re.MULTILINE | re.IGNORECASE))
                            # Response Message for User Request
                            await ctx.followup.send(itemname + " has been removed!", ephemeral=True)
                            # Append changes to embed message
                            return await testmsg.edit(embed=emb)
                        # If Field has only Item as Value
                        else:
                            # Remove entire Field from Embed
                            emb.remove_field(idx)
                            # Response Message for User Request
                            await ctx.followup.send(itemname + " has been removed!", ephemeral=True)
                            # Append changes to embed message
                            return await testmsg.edit(embed=emb)
        # Response Message for User Request
        await ctx.followup.send(itemname + " not found!")

    @removeitemfromuser.error
    async def removeitemfromuser_error(self, ctx, error):
        if isinstance(error, MissingPermissions):
            text = "Sorry {}, you do not have permissions to do that!".format(ctx.message.author)
            await self.bot.send_message(ctx.message.channel, text)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Listmanager(bot))
