"""
A tiny fake of the Discord objects the bot touches, so commands can run end-to-end
without a network connection. Every message the bot would send is recorded in `Recorder`.
"""
from __future__ import annotations

import types
from dataclasses import dataclass, field

import discord

from core.helpers import report_error


@dataclass
class Sent:
    where: str          # "reply", "ephemeral", "channel", "dm:<name>", "webhook:<name>", "edit", "edit#<id>"
    content: str = ""
    embeds: list = field(default_factory=list)
    view: object = None
    id: int = 0
    file: object = None

    async def pin(self):
        pass

    def text(self) -> str:
        parts = [self.content] if self.content else []
        for e in self.embeds:
            if e.author and e.author.name:
                parts.append(f"[{e.author.name}]")
            parts.append(f"**{e.title}**" if e.title else "")
            if e.description:
                parts.append(e.description)
            for f in e.fields:
                parts.append(f"{f.name}: {f.value}")
            if e.footer and e.footer.text:
                parts.append(e.footer.text)
        return "\n".join(p for p in parts if p)


class FakeNamespace(types.SimpleNamespace):
    """Like discord.app_commands.Namespace: options the user hasn't filled in are None."""

    def __getattr__(self, attr):
        return None


class Recorder:
    def __init__(self):
        self.log: list[Sent] = []
        self.messages: dict[int, Sent] = {}   # current state of every message, by id
        self._next_id = 1000

    def add(self, where, content=None, embed=None, embeds=None, view=None, file=None, **_):
        es = list(embeds or []) + ([embed] if embed else [])
        s = Sent(where, content or "", es, view, self._next_id, file)
        self._next_id += 1
        self.log.append(s)
        self.messages[s.id] = s
        return s

    def edit(self, message_id: int, **kw):
        """A live message was edited: log it and update the stored message."""
        msg = self.messages.get(message_id)
        if msg is None:
            raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        if "embed" in kw:
            msg.embeds = [kw["embed"]] if kw["embed"] else []
        if "content" in kw:
            msg.content = kw["content"] or ""
        if "view" in kw:
            msg.view = kw["view"]
        logged = Sent(f"edit#{message_id}", msg.content, list(msg.embeds), msg.view, message_id)
        self.log.append(logged)
        return logged

    @property
    def last(self) -> Sent:
        return self.log[-1]


class FakeUser:
    def __init__(self, rec: Recorder, uid: int, name: str, admin: bool = False):
        self.id, self.display_name, self.name = uid, name, name
        self.mention = f"<@{uid}>"
        self.bot = False
        self.roles = []
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example/{name}.png")
        self.guild_permissions = types.SimpleNamespace(manage_guild=admin)
        self._rec = rec

    async def send(self, content=None, **kw):
        self._rec.add(f"dm:{self.display_name}", content, **kw)


class FakePartialMessage:
    def __init__(self, rec, mid):
        self._rec, self.id = rec, mid

    async def edit(self, **kw):
        self._rec.edit(self.id, **kw)


class FakeChannel:
    def __init__(self, rec: Recorder, cid: int):
        self.id, self.mention, self._rec = cid, f"<#{cid}>", rec

    async def send(self, content=None, **kw):
        return self._rec.add("channel", content, **kw)

    def get_partial_message(self, mid):
        return FakePartialMessage(self._rec, mid)


class FakeBot:
    """Just enough of commands.Bot for the cogs."""

    def __init__(self, db, channels):
        self.db = db
        self.user = types.SimpleNamespace(id=1)
        self._channels = {c.id: c for c in channels}
        self._cogs = {}
        self.persistent_views = []
        self.dynamic_items = []
        from core.table import TableService
        self.table = TableService(self)

    def enable_achievements(self):
        from core.achievements import AchievementService
        self.achievements = AchievementService(self)

    def add_dynamic_items(self, *items):
        self.dynamic_items += items

    def get_channel(self, cid):
        return self._channels.get(cid)

    async def fetch_channel(self, cid):
        raise discord.NotFound(types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Channel")

    def add_view(self, view):
        self.persistent_views.append(view)

    def get_cog(self, name):
        return self._cogs.get(name)

    async def add_cog(self, cog):
        self._cogs[type(cog).__name__] = cog
        if hasattr(cog, "cog_load"):
            await cog.cog_load()


class FakeGuild:
    def __init__(self, gid: int, members: list[FakeUser]):
        self.id = gid
        self._members = {m.id: m for m in members}

    def get_member(self, uid):
        return self._members.get(uid)

    async def fetch_member(self, uid):
        return self._members[uid]


class FakeResponse:
    def __init__(self, inter: "FakeInteraction"):
        self.inter, self._done, self.ephemeral = inter, False, False

    def is_done(self):
        return self._done

    async def send_message(self, content=None, *, ephemeral=False, allowed_mentions=None, **kw):
        assert not self._done, "responded twice to one interaction!"
        self._done, self.ephemeral = True, ephemeral
        self.inter.original = self.inter.rec.add("ephemeral" if ephemeral else "reply", content, **kw)

    async def send_modal(self, modal):
        assert not self._done, "modal after responding!"
        self._done = True
        self.inter.modal = modal
        self.inter.rec.add("modal", f"[modal: {modal.title}]")

    async def autocomplete(self, choices):
        self._done = True
        self.inter.choices = list(choices)

    async def defer(self, *, ephemeral=False, thinking=False):
        assert not self._done, "deferred after responding!"
        self._done, self.ephemeral = True, ephemeral

    async def edit_message(self, content=None, **kw):
        self._done = True
        if self.inter.message is not None:
            if content is not None:
                kw["content"] = content
            self.inter.rec.edit(self.inter.message.id, **kw)
        else:
            self.inter.rec.add("edit", content, **kw)


class FakeFollowup:
    def __init__(self, inter):
        self.inter = inter

    async def send(self, content=None, *, ephemeral=False, wait=False, **kw):
        assert self.inter.response.is_done(), "followup before responding!"
        eph = ephemeral or self.inter.response.ephemeral
        return self.inter.rec.add("ephemeral" if eph else "reply", content, **kw)


class FakeInteraction:
    def __init__(self, rec, user, guild, channel, message=None):
        self.rec, self.user, self.guild, self.channel = rec, user, guild, channel
        self.guild_id, self.channel_id = guild.id, channel.id
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.message = message          # the message a pressed button belongs to
        self.original = None
        self.namespace = FakeNamespace()
        self.modal = None
        self.choices = None
        self.client = None

    async def delete_original_response(self):
        pass

    async def original_response(self):
        return self.original


class FakeWebhook:
    """Stands in for a channel webhook, to test 'post as character'."""

    def __init__(self, rec):
        self.rec = rec

    async def send(self, *, username, avatar_url, thread=None, **kw):
        self.rec.add(f"webhook:{username}", **kw)


class FakeMessage:
    def __init__(self, rec, author, guild, channel, content):
        self.author, self.guild, self.channel, self.content, self._rec = author, guild, channel, content, rec

    async def reply(self, content=None, mention_author=True, **kw):
        self._rec.add("reply", content, **kw)


async def invoke(cmd, cog, inter, **kwargs):
    """Run a slash command callback the way discord.py would, including the global error handler."""
    try:
        await cmd.callback(cog, inter, **kwargs)
    except Exception as e:  # noqa: BLE001 - mirror tree.on_error
        await report_error(inter, discord.app_commands.CommandInvokeError(cmd, e))


async def press(button, inter):
    """Press a button on a view."""
    try:
        await button.callback(inter)
    except Exception as e:  # noqa: BLE001
        await report_error(inter, e)


class FakeAttachment:
    def __init__(self, filename: str, data: bytes):
        self.filename, self._data, self.size = filename, data, len(data)

    async def read(self) -> bytes:
        return self._data


async def submit_modal(modal, inter, **values):
    """Fill in a modal's text inputs (by attribute name) and submit it."""
    for attr, value in values.items():
        getattr(modal, attr)._value = value
    try:
        await modal.on_submit(inter)
    except Exception as e:  # noqa: BLE001
        await modal.on_error(inter, e)


async def autocomplete(cmd, inter, param: str, current: str, **namespace) -> list[str]:
    """Run a command's autocomplete exactly like discord.py does; returns the suggested values."""
    inter.namespace = FakeNamespace(**{param: current, **namespace})
    await cmd._invoke_autocomplete(inter, param, inter.namespace)
    return [c.value for c in (inter.choices or [])]
