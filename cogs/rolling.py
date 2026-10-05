"""Dice rolling: /r, /check, /secret, /pbta, /3d20, inline [[rolls]] and /help."""
from __future__ import annotations

import re
from typing import Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from core.helpers import (
    COLOR_INFO, COLOR_SECRET, BaseView, UserError, WebhookCache, get_campaign, is_gm, load_env,
    require_campaign, send_as, three_d20_embed,
)
from core.achievements import notify
from core.rolls import build_roll, log_roll
from core.stats import check_profile
from core.helptext import CHAPTERS
from core.helptext_de import CHAPTERS_DE
from core.i18n import t
from core.sheet import RollEnv
from dice.engine import DiceError
from dice.systems import three_d20_check

HELP_CHAPTERS = {"en": CHAPTERS, "de": CHAPTERS_DE}
SECRET_MARK = "Secret · "  # title prefix of secret rolls; the GM's Reveal button swaps it for "Revealed · "
INLINE_RE = re.compile(r"\[\[(.+?)\]\]")
# Words people start a mention roll with, in a few languages:
# "@Bot roll for shooting & dex", "@Bot würfel auf schiessen", "@Bot lance pour tir et dex", "@Bot tira 5"
MENTION_VERBS = (
    r"roll|rolls|rolle|rollen|r|check\w*|throw|toss"         # English (+ German-ish "checke", "rollen")
    r"|w[üu]rf\w*|wuerf\w*|wirf|probe|pr[üu]f\w*|pruef\w*"   # German: würfel, würfle, würfeln, wirf, prüfe
    r"|lance\w*|jet|jette\w*"                                # French: lance, lancer, jet
    r"|tira\w*|lanza\w*|lancia\w*"                           # Spanish / Italian: tira, tirar, lanza, lancia
    r"|gooi|werp|rol"                                        # Dutch
    r"|rola|rolar|joga|jogar"                                # Portuguese
)
MENTION_FOR = r"for|auf|f[üu]r|fuer|mit|pour|para|per|voor|com|con"  # "roll for …", "würfel auf …"
MENTION_VERB_RE = re.compile(rf"^(?:{MENTION_VERBS})\b\s*(?:(?:{MENTION_FOR})\b\s*)?", re.I)
MENTION_HELP = {"help", "hilfe", "aide", "ayuda", "aiuto", "hulp", "ajuda", "?"}
W_COUNT_RE = re.compile(r"^w(\d{1,3})$", re.I)  # "w5": five dice with the campaign rules (W = Würfel)
ADVANTAGE_CHOICES = [Choice(name="Advantage", value="adv"), Choice(name="Disadvantage", value="dis")]


class RollView(BaseView):
    """Reroll button; only the original roller can use it."""

    def __init__(self, cog: "Rolling", owner_id: int, text: str, advantage: Optional[str], modifier: int = 0,
                 pbta: bool = False):
        super().__init__(timeout=1800)
        self.cog, self.owner_id, self.text = cog, owner_id, text
        self.advantage, self.modifier, self.pbta = advantage, modifier, pbta

    @discord.ui.button(label="Reroll", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person who rolled can reroll this.", ephemeral=True)
            return
        await self.cog.public_roll(interaction, self.text, self.advantage, self.modifier, self.pbta)


class RevealView(BaseView):
    """Lets the GM reveal a secret roll to the table."""

    def __init__(self, embed: discord.Embed):
        super().__init__(timeout=3600)
        self.embed = embed

    @discord.ui.button(label="Reveal to table", style=discord.ButtonStyle.primary)
    async def reveal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.embed.title = (self.embed.title or "").replace(SECRET_MARK, "Revealed · ", 1)
        await interaction.response.send_message(embed=self.embed)
        self.stop()


def with_sentence(embed: discord.Embed, sentence: str):
    """Swap the card's big result line ("# 1 Success") for the player's own sentence with the result in it."""
    lines = (embed.description or "").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i] = f"### {sentence}"
            break
    else:
        lines.append(f"### {sentence}")
    embed.description = "\n".join(lines)[:4096]


class HelpView(BaseView):
    """The /help chapters: a menu to pick one, plus back/next buttons."""

    def __init__(self, bot_id: int, key: str, lang: str = "en"):
        super().__init__(timeout=900)
        self.bot_id, self.key, self.lang = bot_id, key, lang
        self.chapters = HELP_CHAPTERS.get(lang, CHAPTERS)
        self.by_key = {c.key: c for c in self.chapters}
        self.menu = discord.ui.Select(placeholder=t(lang, "Choose a chapter…"), row=0, options=[
            discord.SelectOption(label=c.title, value=c.key, description=c.summary)
            for c in self.chapters])
        self.menu.callback = self.pick
        self.add_item(self.menu)
        self.back.label, self.next_page.label = "‹ " + t(lang, "Back"), t(lang, "Next") + " ›"
        self._mark()

    def _mark(self):
        for option in self.menu.options:
            option.default = option.value == self.key

    def page(self) -> discord.Embed:
        chapter = self.by_key[self.key]
        n = self.chapters.index(chapter)
        e = discord.Embed(title=chapter.title, color=COLOR_INFO,
                          description=chapter.text.strip().replace("{me}", f"<@{self.bot_id}>"))
        e.set_footer(text=t(self.lang, "Chapter {n} of {total} · pick another one in the menu below",
                            n=n + 1, total=len(self.chapters)))
        return e

    async def show(self, interaction: discord.Interaction, key: str):
        self.key = key
        self._mark()
        await interaction.response.edit_message(embed=self.page(), view=self)

    async def pick(self, interaction: discord.Interaction):
        await self.show(interaction, self.menu.values[0])

    def _step(self, by: int) -> str:
        keys = [c.key for c in self.chapters]
        return keys[(keys.index(self.key) + by) % len(keys)]

    @discord.ui.button(label="‹ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show(interaction, self._step(-1))

    @discord.ui.button(label="Next ›", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.show(interaction, self._step(1))


class Rolling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.hooks = WebhookCache(bot)

    # ------------------------------------------------------------------ core

    @staticmethod
    def build(env: RollEnv, user, text: str, advantage: Optional[str] = None, modifier: int = 0,
              pbta: bool = False) -> tuple[discord.Embed, dict]:
        return build_roll(env, user, text, advantage, modifier, pbta)

    async def log(self, data: dict, *, guild_id, channel_id, campaign, user_id, env: RollEnv, secret=False,
                  channel=None):
        await log_roll(self.db, data, guild_id=guild_id, channel_id=channel_id, campaign=campaign,
                       user_id=user_id, env=env, secret=secret)
        if not secret:
            await notify(self.bot, guild_id, [user_id], channel)

    async def public_roll(self, interaction: discord.Interaction, text: str, advantage: Optional[str] = None,
                          modifier: int = 0, pbta: bool = False):
        campaign = await get_campaign(self.db, interaction.channel)
        env = await load_env(self.db, campaign, interaction.user.id, interaction.guild_id)
        embed, data = self.build(env, interaction.user, text, advantage, modifier, pbta)
        view = RollView(self, interaction.user.id, text, advantage, modifier, pbta)
        await send_as(interaction, self.hooks, campaign, env.character, embed, view)
        await self.log(data, guild_id=interaction.guild_id, channel_id=interaction.channel_id,
                       campaign=campaign, user_id=interaction.user.id, env=env, channel=interaction.channel)

    # ------------------------------------------------------------------ commands

    @app_commands.command(name="r", description="Roll dice: 2d6+3, 1d20+dex, 4d6kh3, 6d10>=8, 4dF, or a skill/macro name")
    @app_commands.describe(expression="What to roll. Add '# text' for a label, e.g. 1d20+5 # attack",
                           advantage="Roll the d20 twice and keep the higher/lower")
    @app_commands.choices(advantage=ADVANTAGE_CHOICES)
    async def r(self, interaction: discord.Interaction, expression: str, advantage: Optional[Choice[str]] = None):
        await self.public_roll(interaction, expression, advantage.value if advantage else None)

    @app_commands.command(name="check", description="Roll one of your character's skills")
    @app_commands.describe(skill="Skill name. With campaign dice rules also a dice count or combo: 5, shooting & dex",
                           modifier="Bonus/penalty (campaign dice rules: extra dice; 3d20: added to each attribute)",
                           advantage="Advantage / disadvantage on the d20")
    @app_commands.choices(advantage=ADVANTAGE_CHOICES)
    async def check(self, interaction: discord.Interaction, skill: str, modifier: int = 0,
                    advantage: Optional[Choice[str]] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        env = await load_env(self.db, campaign, interaction.user.id, interaction.guild_id)
        text = skill.strip()
        name = text.lower()
        is_skill = bool(env.sheet and name in env.sheet.skills)
        # With campaign dice rules, numbers and combos like "shooting & dex" work too
        if not is_skill and not (env.rules and env.dice_count(text) is not None):
            if not env.sheet:
                raise UserError("You don't have an active character here. Use `/char create` or `/char use`.")
            raise UserError(f"**{env.character.name}** has no skill `{name}`. Add it with `/skill add`.")
        await self.public_roll(interaction, name if is_skill else text, advantage.value if advantage else None,
                               modifier)

    @check.autocomplete("skill")
    async def skill_autocomplete(self, interaction: discord.Interaction, current: str):
        campaign = await get_campaign(self.db, interaction.channel)
        if not campaign:
            return []
        character = await self.db.get_active_character(campaign.id, interaction.user.id)
        if not character:
            return []
        skills = await self.db.get_skills(character.id)
        return [Choice(name=f"{n} · {s.describe()}"[:100], value=n)
                for n, s in skills.items() if current.lower() in n][:25]

    @app_commands.command(name="secret", description="Secret roll: only the GM sees the result")
    @app_commands.describe(expression="What to roll (dice, skill or macro)", advantage="Advantage / disadvantage")
    @app_commands.choices(advantage=ADVANTAGE_CHOICES)
    async def secret(self, interaction: discord.Interaction, expression: str, advantage: Optional[Choice[str]] = None):
        campaign = await require_campaign(self.db, interaction.channel)
        env = await load_env(self.db, campaign, interaction.user.id, interaction.guild_id)
        embed, data = self.build(env, interaction.user, expression, advantage.value if advantage else None)
        embed.title = SECRET_MARK + (embed.title or "")
        embed.color = COLOR_SECRET
        who = env.character.name if env.character else interaction.user.display_name

        if is_gm(interaction.user, campaign):
            await interaction.response.send_message(embed=embed, ephemeral=True, view=RevealView(embed))
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            gm = interaction.guild.get_member(campaign.gm_user_id)
            if gm is None:
                try:
                    gm = await interaction.guild.fetch_member(campaign.gm_user_id)
                except discord.HTTPException:
                    raise UserError("I can't find the GM of this campaign on this server.")
            try:
                await gm.send(t(campaign.language, "Secret roll from **{who}** in {channel}", who=who,
                                channel=interaction.channel.mention), embed=embed)
            except discord.HTTPException:
                raise UserError("I couldn't DM the GM. They need to allow DMs from server members.")
            await interaction.channel.send(
                t(campaign.language, "**{who}** made a secret roll… only the GM knows the result.", who=who))
            await interaction.followup.send(t(campaign.language, "Sent to the GM."), ephemeral=True)

        await self.log(data, guild_id=interaction.guild_id, channel_id=interaction.channel_id,
                       campaign=campaign, user_id=interaction.user.id, env=env, secret=True)

    @app_commands.command(name="pbta", description="Powered by the Apocalypse move: 2d6 + modifier")
    @app_commands.describe(modifier="Stat or number, e.g. cool, 2, -1", label="Name of the move")
    async def pbta(self, interaction: discord.Interaction, modifier: str = "0", label: Optional[str] = None):
        text = f"2d6 + ({modifier}) # {label or 'Move'}"
        await self.public_roll(interaction, text, pbta=True)

    @app_commands.command(name="3d20", description="3d20 attribute check (DSA style) with raw numbers")
    @app_commands.describe(attr1="First attribute value", attr2="Second attribute value",
                           attr3="Third attribute value", points="Skill points",
                           modifier="Added to every attribute (negative = harder)", label="What you're checking")
    async def three_d20(self, interaction: discord.Interaction, attr1: int, attr2: int, attr3: int,
                        points: int, modifier: int = 0, label: Optional[str] = None):
        res = three_d20_check([("A1", attr1), ("A2", attr2), ("A3", attr3)], points, modifier)
        embed = three_d20_embed(res, label or "3d20 check", interaction.user, None)
        await interaction.response.send_message(embed=embed)
        await self.db.log_roll(guild_id=interaction.guild_id, channel_id=interaction.channel_id, campaign_id=None,
                               user_id=interaction.user.id, character_id=None,
                               expression=f"3d20:{attr1}/{attr2}/{attr3}:{points}", label=label,
                               total=res.remaining, natural=None, **check_profile(res))

    # ------------------------------------------------------------------ inline rolls & talking to the bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        me = self.bot.user
        if me and "[[" not in message.content and re.match(rf"^\s*<@!?{me.id}>", message.content):
            await self.mention_roll(message)
            return
        if "[[" not in message.content:
            return
        matches = INLINE_RE.findall(message.content)[:5]
        if not matches:
            return
        campaign = await get_campaign(self.db, message.channel)
        env = await load_env(self.db, campaign, message.author.id, message.guild.id)
        embeds, phrases = [], []
        for text in matches:
            try:
                embed, data = self.build(env, message.author, text)
                await self.log(data, guild_id=message.guild.id, channel_id=message.channel.id,
                               campaign=campaign, user_id=message.author.id, env=env, channel=message.channel)
                phrases.append(data["phrase"])
            except DiceError as e:
                embed = discord.Embed(description=f"`{text}`: {e}", color=discord.Color.orange())
                phrases.append(None)
            embeds.append(embed)

        # The message itself, with every [[roll]] replaced by its result: "I make **1 Success ✨** backflips!"
        results = iter(phrases)
        sentence = INLINE_RE.sub(lambda m: f"**{p}**" if (p := next(results, None)) else m.group(0),
                                 message.content)
        sentence = " ".join(sentence.split())[:1000]
        content = None
        if len(embeds) == 1:
            if phrases[0]:
                with_sentence(embeds[0], sentence)
        elif any(phrases):
            content = re.sub(r" ?[✨🍀💤]", "", sentence)
        view = RollView(self, message.author.id, matches[0], None) if len(matches) == 1 else None
        await message.reply(content, embeds=embeds, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none(), **({"view": view} if view else {}))

    async def mention_roll(self, message: discord.Message):
        """'@Bot roll shooting & dex', '@Bot w5', '@Bot 2d6+3', '@Bot pool(7)'."""
        text = re.sub(rf"^\s*<@!?{self.bot.user.id}>[\s,:]*", "", message.content).strip()
        text = MENTION_VERB_RE.sub("", text, count=1).strip()
        w = W_COUNT_RE.match(text)
        if w:
            text = w.group(1)
        campaign = await get_campaign(self.db, message.channel)
        lang = campaign.language if campaign else "en"
        if not text or text.lower() in MENTION_HELP:
            me = f"<@{self.bot.user.id}>"
            await message.reply("\n".join([
                "🎲 " + t(lang, "Talk to me to roll: {me} `roll shooting & dex` · {me} `check 10` · {me} `w5` · "
                        "{me} `2d6+3` · {me} `pool(7)`", me=me),
                t(lang, "Works in other languages too: `würfel auf schiessen und ge` · `lance 5` · `tira 5`"),
                t(lang, "Everything else is in `/help`."),
            ]), mention_author=False)
            return
        env = await load_env(self.db, campaign, message.author.id, message.guild.id)
        try:
            # "w5" / "roll 10" mean a number of campaign dice; without dice rules that's just the number
            if not env.rules and re.fullmatch(r"\d+", text):
                raise UserError(t(lang, "`{n}` dice need the campaign's dice rules, and this channel has none yet. "
                                        "The GM can set them with `/campaign dice`, or roll e.g. `{n}d10`.", n=text))
            embed, data = self.build(env, message.author, text)
        except (DiceError, UserError) as e:
            await message.reply(f"{e}", mention_author=False)
            return
        await message.reply(embed=embed, view=RollView(self, message.author.id, text, None), mention_author=False)
        await self.log(data, guild_id=message.guild.id, channel_id=message.channel.id, campaign=campaign,
                       user_id=message.author.id, env=env, channel=message.channel)

    # ------------------------------------------------------------------ help

    @app_commands.command(name="help", description="How to use the bot, explained in chapters")
    @app_commands.describe(chapter="Jump straight to a chapter")
    @app_commands.choices(chapter=[Choice(name=c.title, value=c.key) for c in CHAPTERS])
    async def help(self, interaction: discord.Interaction, chapter: Optional[Choice[str]] = None):
        key = chapter.value if chapter else CHAPTERS[0].key
        campaign = await get_campaign(self.db, interaction.channel)
        if campaign:
            lang = campaign.language
        else:  # outside a campaign: the language of the user's Discord app
            lang = "de" if str(getattr(interaction, "locale", "")).startswith("de") else "en"
        view = HelpView(self.bot.user.id, key, lang)
        await interaction.response.send_message(embed=view.page(), view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Rolling(bot))
