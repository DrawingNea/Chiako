import discord
from discord.ext import commands
from discord import app_commands
import mysql.connector
from mysql.connector import Error
from discord.ext.commands import has_permissions, MissingPermissions


class Rolecolormanager(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setuserrole", description="Change color of a role")
    @has_permissions(administrator=True)
    async def enableusertochangerolecolorandname(self, ctx, user: discord.Member, role: discord.Role, dmuser: bool = False):
        await ctx.response.defer()
        # Fetch user from server by username
        member = discord.utils.get(ctx.user.guild.members, name=user.name)
        # if no user with username was found
        if (member == None):
            # Response Message for User Request
            await ctx.followup.send("Member does not exist!")
            return
        # Fetch role from user by rolename
        role = discord.utils.get(member.guild.roles, name=role.name)
        # if no role with rolename was found
        if (role == None):
            # Response Message for User Request
            await ctx.followup.send("Role does not exist!")
            return
        else:
            userid = member.id
            # create string to write to db consisting of server id and role id
            serverid = ctx.guild.id
            # get array of all keys from DB
            cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
            cursor = await cnx.cursor()
            await cursor.execute("SELECT ServerID, UserID, RoleID FROM RoleColorChanger")
            dbarray = await cursor.fetchall()
            # User has no entry in DB
            if (any(userid in dbentry for dbentry in dbarray)):
                # saving to DB the user id  and string consisting of server id and role id
                await cursor.execute("INSERT INTO RoleColorChanger (ServerID, UserID, RoleID) VALUES (%s, %s, %s)"
                               % (str(serverid), str(userid), str(role.id)))
                cnx.commit()
                # Response Message for User Request
                await ctx.followup.send("Enabled color change of " + role.name + " for User " + member.name)
                if(dmuser):
                    await member.send(ctx.message.author.name + " setup the role " + role.name +
                                      " for you to customize!\nGo ahead and try it out!")
                return
            # split into array of each server & role strings
            allserverroles = dbarray
            # Look through every entry if Server has set Role
            for entry in allserverroles:
                # split into array of server id and role id
                entryserverid = entry[0]
                entryuserid = entry[1]
                entryroleid = entry[2]
                # Server already has set Role
                if str(entryserverid) == str(serverid):
                    if (str(entryuserid) == str(userid)):
                        print("Server already has set Role")
                        # add new string to DB entry and save to DB
                        await cursor.execute("UPDATE RoleColorChanger SET RoleID = %s WHERE ServerID = %s AND UserID = %s" % (
                        str(role.id), str(serverid), str(userid)))
                        cnx.commit()
                        # Response Message for User Request
                        await ctx.followup.send("Enabled color change of " + role.name + " for User " + member.name)
                        if(dmuser):
                            await member.send(ctx.message.author.name + " just changed your custom role to " + role.name +
                                      "!\n Come and take a look!")
                        return
            # Server has not set Role yet, add Server and Role to DB
            print("Server has not set Role yet, add Server and Role to DB")
            # add new string to DB entry and save to DB
            await cursor.execute("INSERT INTO RoleColorChanger(ServerID,UserID,RoleID) VALUES (%s,%s,%s)" % (
            str(serverid), str(userid), str(role.id)))
            cnx.commit()
            # Response Message for User Request
            await ctx.followup.send("Enabled color change of " + role.name + " for User " + member.name)

    @app_commands.command(name="changecolor", description="Change color of your role")
    async def changerolecolor(self, ctx, hexcolor: str):
        await ctx.response.defer()
        userid = ctx.user.id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT ServerID, UserID, RoleID FROM RoleColorChanger")
        dbarray = await cursor.fetchall()
        for entry in dbarray:
            entryserverid = entry[0]
            entryuserid = entry[1]
            entryroleid = entry[2]
            if (entryserverid == str(ctx.guild.id)):
                role = discord.utils.get(ctx.user.guild.roles, id=int(entryroleid))
                if (role != None):
                    try:
                        await ctx.user.add_roles(role)
                        await role.edit(colour=int(hexcolor, 16))
                        await ctx.followup.send("Color of role changed!")
                        return
                    except discord.errors.Forbidden:
                        await ctx.followup.send("I am missing permissions")
                        return

        await ctx.followup.send("You don't have a customizable role...")

    @app_commands.command(name="changename", description="Change name of your role")
    async def changerolename(self, ctx, rolename: str):
        await ctx.response.defer()
        userid = ctx.user.id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT ServerID, UserID, RoleID FROM RoleColorChanger")
        dbarray = await cursor.fetchall()
        for entry in dbarray:
            entryserverid = entry[0]
            entryuserid = entry[1]
            entryroleid = entry[2]
            if (entryserverid == str(ctx.guild.id)):
                role = discord.utils.get(ctx.user.guild.roles, id=int(entryroleid))
                if (role != None):
                    try:
                        await ctx.user.add_roles(role)
                        await role.edit(name=rolename)
                        await ctx.followup.send("Name of role changed!")
                        return
                    except discord.errors.Forbidden:
                        await ctx.followup.send("I am missing permissions")
                        return

        await ctx.followup.send("No one found with role")

    @app_commands.command(name="resetuser", description="Change color of your role")
    @has_permissions(administrator=True)
    async def resetuserforserver(self, ctx, user: discord.Member):
        await ctx.response.defer()
        userid = discord.utils.get(ctx.user.guild.members, name=user.name).id
        cnx = await self.bot.database.get_connection() # Accessing the bot's DB connection
        cursor = await cnx.cursor()
        await cursor.execute("SELECT ServerID, UserID, RoleID FROM RoleColorChanger")
        dbarray = await cursor.fetchall()
        for entry in dbarray:
            entryserverid = entry[0]
            entryuserid = entry[1]
            entryroleid = entry[2]
            if (entryserverid == str(ctx.guild.id)):
                cursor.execute("DELETE FROM RoleColorChanger WHERE ServerID = %s AND UserID = %s" % (
                str(ctx.guild.id), str(userid)))
                cnx.commit()
                await ctx.followup.send("Removed colorchange")
                return
        await ctx.followup.send("No one found with role")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Rolecolormanager(bot))
