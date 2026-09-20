from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from .commands_core import register_core
from .commands_story import register_story
from .config import Settings
from .crypto import Cipher
from .db import Database
from .llm import LLMClient

log = logging.getLogger("calliope")


class Calliope(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.db = Database(settings.database_path, Cipher(settings.encryption_key), settings.raw_retention_days)
        self.llm = LLMClient(settings)
        self.tree = app_commands.CommandTree(self)
        self.group = app_commands.Group(name="calliope", description="Iris Calliope story archive controls")
        self.channels = app_commands.Group(name="channel", description="Manage watched roleplay channels", parent=self.group)
        self.sources = app_commands.Group(name="source", description="Manage trusted Tupperbox webhook sources", parent=self.group)
        register_core(self)
        register_story(self)

    async def setup_hook(self) -> None:
        await self.db.connect()
        self.tree.add_command(self.group)
        await self.tree.sync()
        self.summarize_pending.start()
        self.retention_cleanup.start()

    async def close(self) -> None:
        self.summarize_pending.cancel()
        self.retention_cleanup.cancel()
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Iris Calliope connected as %s", self.user)
        log.info("Connected to %s server(s)", len(self.guilds))
        for guild in self.guilds:
            log.info("- %s — %s", guild.name, guild.id)

    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not message.webhook_id or not message.content:
            return
        if not await self.db.is_watched(message.guild.id, message.channel.id):
            return
        if not await self.db.is_trusted_webhook(message.guild.id, message.webhook_id):
            return
        await self.db.store_raw_message(message.guild.id, message.channel.id, message.id, message.webhook_id, message.author.display_name, message.content, message.created_at)

    @tasks.loop(hours=6)
    async def summarize_pending(self) -> None:
        if not self.settings.llm_enabled:
            return
        for guild_id, channel_id in await self.db.unsummarized_groups(self.settings.summary_min_messages):
            rows = await self.db.get_unsummarized(guild_id, channel_id)
            if not rows:
                continue
            transcript = "\n".join(f"{row['character']}: {row['content']}" for row in rows)
            try:
                summary = await self.llm.summarize(transcript)
            except Exception:
                log.exception("Summary failed for guild=%s channel=%s", guild_id, channel_id)
                continue
            await self.db.save_summary(guild_id, channel_id, rows[0]["created_at"], rows[-1]["created_at"], summary, [row["id"] for row in rows])

    @summarize_pending.before_loop
    async def before_summarize(self) -> None:
        await self.wait_until_ready()
        self.summarize_pending.change_interval(hours=self.settings.summary_interval_hours)

    @tasks.loop(hours=1)
    async def retention_cleanup(self) -> None:
        deleted = await self.db.delete_expired()
        if deleted:
            log.info("Deleted %s expired raw RP message(s)", deleted)

    @retention_cleanup.before_loop
    async def before_cleanup(self) -> None:
        await self.wait_until_ready()
