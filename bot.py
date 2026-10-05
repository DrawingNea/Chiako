"""Pen & paper dice bot: entry point."""
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from core.db import Database
from core.helpers import report_error
from core.achievements import AchievementService
from core.table import TableService

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dicebot")

EXTENSIONS = ("cogs.campaigns", "cogs.characters", "cogs.rolling", "cogs.combat", "cogs.health",
              "cogs.groupcheck", "cogs.progress", "cogs.companions", "cogs.lore", "cogs.sessions",
              "cogs.schedule", "cogs.inventory")


def make_database() -> Database:
    """MySQL/MariaDB when DB_HOST is set, otherwise a local SQLite file."""
    host = os.getenv("DB_HOST")
    if not host:
        return Database(os.getenv("DATABASE_PATH", "dicebot.db"))
    missing = [k for k in ("DB_USER", "DB_NAME") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"DB_HOST is set but {', '.join(missing)} is missing in .env.")
    log.info("Using MySQL database %s on %s", os.getenv("DB_NAME"), host)
    return Database(mysql=dict(host=host, port=int(os.getenv("DB_PORT") or 3306), user=os.getenv("DB_USER"),
                               password=os.getenv("DB_PASS", ""), db=os.getenv("DB_NAME")))


class DiceBot(commands.Bot):
    def __init__(self, message_content: bool = True):
        intents = discord.Intents.default()
        intents.message_content = message_content  # needed for inline [[rolls]]
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.db = make_database()
        self.table = TableService(self)
        self.achievements = AchievementService(self)
        self.tree.on_error = report_error

    async def setup_hook(self):
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        dev_guild = os.getenv("DEV_GUILD_ID")
        if dev_guild:
            # Instant command updates on your test server
            guild = discord.Object(int(dev_guild))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            # Global sync: can take a while to show up the first time
            synced = await self.tree.sync()
        log.info("Synced %d slash commands", len(synced))

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game("with dice · /help"))

    async def close(self):
        await self.db.close()
        await super().close()


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN missing. Copy .env.example to .env and fill it in.")
    try:
        DiceBot().run(token, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        log.warning("Message Content Intent is not enabled for this bot in the developer portal "
                    "(Bot -> Privileged Gateway Intents). Running without it: inline [[rolls]] are disabled.")
        DiceBot(message_content=False).run(token, log_handler=None)


if __name__ == "__main__":
    main()
