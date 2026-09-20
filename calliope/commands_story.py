from __future__ import annotations

from difflib import get_close_matches

import discord
from discord import app_commands

from .commands_core import is_admin


def _normalize_character_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _message_url(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def _message_preview(content: str, limit: int = 320) -> str:
    compact = " ".join(content.split())
    if len(compact) > limit:
        compact = compact[: limit - 1].rstrip() + "…"
    return discord.utils.escape_markdown(discord.utils.escape_mentions(compact))


def _found_text(requester_id: int, row: dict) -> str:
    character = discord.utils.escape_markdown(row["character"])
    when = discord.utils.format_dt(row["created_at"], style="R")
    preview = _message_preview(row["content"])
    return f"<@{requester_id}>, I found **{character}**.\nLast seen in <#{row['channel_id']}> {when}.\n\n> {preview}"


class JumpToMessageView(discord.ui.View):
    def __init__(self, url: str) -> None:
        super().__init__(timeout=300)
        self.add_item(discord.ui.Button(label="Jump to message", url=url))


class ConfirmCharacterView(discord.ui.View):
    def __init__(self, requester_id: int, guild_id: int, candidate: str, row: dict) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.guild_id = guild_id
        self.candidate = candidate
        self.row = row

    async def _check_requester(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message("This confirmation belongs to the person who ran the command.", ephemeral=True)
        return False

    @discord.ui.button(label="Yes, find them", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_requester(interaction):
            return
        url = _message_url(self.guild_id, self.row["channel_id"], self.row["message_id"])
        await interaction.response.edit_message(content=_found_text(self.requester_id, self.row), view=JumpToMessageView(url))

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._check_requester(interaction):
            return
        await interaction.response.edit_message(content="Okay — try /calliope find again with another character name.", view=None)


def register_story(bot) -> None:
    @bot.group.command(name="suggest", description="Suggest likely RP channels without storing their history")
    async def suggest(interaction: discord.Interaction) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        me = interaction.guild.me
        suggestions: list[tuple[str, int]] = []
        if me:
            for channel in interaction.guild.text_channels:
                perms = channel.permissions_for(me)
                if not (perms.view_channel and perms.read_message_history):
                    continue
                count = 0
                try:
                    async for message in channel.history(limit=bot.settings.suggest_history_limit):
                        if message.webhook_id:
                            count += 1
                except discord.Forbidden:
                    continue
                if count:
                    suggestions.append((channel.mention, count))
        suggestions.sort(key=lambda item: item[1], reverse=True)
        if suggestions:
            body = "\n".join(f"• {name} — {count} recent webhook message(s)" for name, count in suggestions[:15])
            body += "\n\nNothing from this scan was stored or summarized. Confirm a known Tupperbox proxy before trusting its source."
        else:
            body = "No recent webhook activity was found. Nothing from this scan was stored."
        await interaction.followup.send(body, ephemeral=True)

    @bot.sources.command(name="trust-message", description="Trust the webhook used by a known Tupperbox proxy")
    async def trust_message(interaction: discord.Interaction, channel: discord.TextChannel, message_id: str) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden):
            await interaction.response.send_message("I could not fetch that message.", ephemeral=True)
            return
        if not message.webhook_id:
            await interaction.response.send_message("That message was not sent through a webhook.", ephemeral=True)
            return
        await bot.db.trust_webhook(interaction.guild.id, message.webhook_id)
        await interaction.response.send_message(f"Trusted webhook {message.webhook_id}. Only trusted webhook sources can enter Calliope's archive.", ephemeral=True)

    @bot.sources.command(name="remove", description="Remove a trusted Tupperbox webhook")
    async def source_remove(interaction: discord.Interaction, webhook_id: str) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        try:
            await bot.db.untrust_webhook(interaction.guild.id, int(webhook_id))
        except ValueError:
            await interaction.response.send_message("Webhook ID must be numeric.", ephemeral=True)
            return
        await interaction.response.send_message("Webhook trust removed.", ephemeral=True)

    @bot.sources.command(name="list", description="List trusted Tupperbox webhook IDs")
    async def source_list(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        ids = await bot.db.list_webhooks(interaction.guild.id)
        await interaction.response.send_message("\n".join(f"• {i}" for i in ids) if ids else "No trusted webhook IDs.", ephemeral=True)

    @bot.group.command(name="find", description="Find a character's most recent retained RP message")
    @app_commands.describe(character="Character name to look for")
    async def find_character(interaction: discord.Interaction, character: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return

        watched_ids = await bot.db.list_channels(interaction.guild.id)
        visible_ids: list[int] = []
        for channel_id in watched_ids:
            channel = interaction.guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel) and channel.permissions_for(interaction.user).view_channel:
                visible_ids.append(channel_id)

        rows = await bot.db.recent_character_messages(interaction.guild.id, visible_ids)
        if not rows:
            await interaction.response.send_message("I don't have any retained Tupperbox roleplay from channels you can view yet.", ephemeral=True)
            return

        query = _normalize_character_name(character)
        latest_by_name: dict[str, dict] = {}
        display_names: dict[str, str] = {}
        for row in rows:
            key = _normalize_character_name(row["character"])
            if key and key not in latest_by_name:
                latest_by_name[key] = row
                display_names[key] = row["character"]

        if query in latest_by_name:
            row = latest_by_name[query]
            url = _message_url(interaction.guild.id, row["channel_id"], row["message_id"])
            await interaction.response.send_message(
                _found_text(interaction.user.id, row),
                view=JumpToMessageView(url),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            return

        closest = get_close_matches(query, list(latest_by_name.keys()), n=1, cutoff=0.6)
        if not closest:
            await interaction.response.send_message(
                f"I don't recognize **{discord.utils.escape_markdown(character)}** in my current 7-day memory, and I couldn't find a close match.",
                ephemeral=True,
            )
            return

        key = closest[0]
        candidate = display_names[key]
        row = latest_by_name[key]
        view = ConfirmCharacterView(interaction.user.id, interaction.guild.id, candidate, row)
        await interaction.response.send_message(
            f"<@{interaction.user.id}>, I don't know **{discord.utils.escape_markdown(character)}**. Did you mean **{discord.utils.escape_markdown(candidate)}**?",
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @bot.group.command(name="summary", description="Read recent Calliope chronicle entries")
    async def summary(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        rows = await bot.db.recent_summaries(interaction.guild.id, 5)
        if not rows:
            await interaction.response.send_message("Calliope has not written a chronicle entry yet.", ephemeral=True)
            return
        text = "\n\n".join(f"**<#{row['channel_id']}>**\n{row['summary']}" for row in reversed(rows))
        await interaction.response.send_message(text[-1900:], ephemeral=True)
