from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import get_close_matches

import discord
from discord import app_commands

from .commands_core import is_admin


FIND_HISTORY_WINDOWS = ((7, 20), (20, 30), (30, 60), (60, 90), (90, 180), (180, 365))


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


def _history_row(message: discord.Message) -> dict:
    return {
        "channel_id": message.channel.id,
        "message_id": message.id,
        "character": message.author.display_name,
        "content": message.content,
        "created_at": message.created_at,
    }


def _safe_name(value: str) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value))


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


async def _visible_watched_channels(bot, interaction: discord.Interaction) -> list[discord.TextChannel]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return []
    watched_ids = await bot.db.list_channels(interaction.guild.id)
    channels: list[discord.TextChannel] = []
    for channel_id in watched_ids:
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        permissions = channel.permissions_for(interaction.user)
        if permissions.view_channel and permissions.read_message_history:
            channels.append(channel)
    return channels


async def _search_older_history(bot, guild: discord.Guild, channels: list[discord.TextChannel], query: str, candidates: dict[str, dict]) -> dict | None:
    trusted_webhooks = set(await bot.db.list_webhooks(guild.id))
    if not trusted_webhooks:
        return None

    now = datetime.now(timezone.utc)
    for newer_days, older_days in FIND_HISTORY_WINDOWS:
        after = now - timedelta(days=older_days)
        before = now - timedelta(days=newer_days)
        exact_match: dict | None = None

        for channel in channels:
            try:
                async for message in channel.history(limit=None, after=after, before=before, oldest_first=False):
                    if not message.webhook_id or message.webhook_id not in trusted_webhooks or not message.content:
                        continue
                    row = _history_row(message)
                    key = _normalize_character_name(row["character"])
                    if key and (key not in candidates or row["created_at"] > candidates[key]["created_at"]):
                        candidates[key] = row
                    if key == query and (exact_match is None or row["created_at"] > exact_match["created_at"]):
                        exact_match = row
            except (discord.Forbidden, discord.HTTPException):
                continue

        if exact_match is not None:
            return exact_match

    return None


def _split_character_pages(names: list[str], limit: int = 1700) -> list[str]:
    pages: list[str] = []
    current = ""
    for name in names:
        line = f"• {_safe_name(name)}\n"
        if current and len(current) + len(line) > limit:
            pages.append(current.rstrip())
            current = ""
        current += line
    if current:
        pages.append(current.rstrip())
    return pages


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

    @bot.group.command(name="characters", description="List character names Calliope has learned from Tupperbox RP")
    async def characters(interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channels = await _visible_watched_channels(bot, interaction)
        names = await bot.db.list_characters(interaction.guild.id, [channel.id for channel in channels])
        if not names:
            await interaction.followup.send("I don't know any characters from watched channels you can view yet.", ephemeral=True)
            return
        pages = _split_character_pages(names)
        for index, page in enumerate(pages, start=1):
            heading = f"**Characters Calliope knows — {len(names)} total**"
            if len(pages) > 1:
                heading += f" · page {index}/{len(pages)}"
            await interaction.followup.send(f"{heading}\n{page}", ephemeral=True)

    @bot.group.command(name="find", description="Find a character's most recent RP message")
    @app_commands.describe(character="Character name to look for")
    async def find_character(interaction: discord.Interaction, character: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        channels = await _visible_watched_channels(bot, interaction)
        if not channels:
            await interaction.followup.send("There are no watched channels you can search.", ephemeral=True)
            return

        visible_ids = [channel.id for channel in channels]
        rows = await bot.db.recent_character_messages(interaction.guild.id, visible_ids)
        query = _normalize_character_name(character)
        candidates: dict[str, dict] = {}

        for row in rows:
            key = _normalize_character_name(row["character"])
            if key and key not in candidates:
                candidates[key] = row

        if query in candidates:
            row = candidates[query]
            url = _message_url(interaction.guild.id, row["channel_id"], row["message_id"])
            await interaction.followup.send(
                _found_text(interaction.user.id, row),
                view=JumpToMessageView(url),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            return

        row = await _search_older_history(bot, interaction.guild, channels, query, candidates)
        if row is not None:
            url = _message_url(interaction.guild.id, row["channel_id"], row["message_id"])
            await interaction.followup.send(
                _found_text(interaction.user.id, row),
                view=JumpToMessageView(url),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            return

        closest = get_close_matches(query, list(candidates.keys()), n=1, cutoff=0.6)
        if not closest:
            await interaction.followup.send(
                f"I couldn't find **{discord.utils.escape_markdown(character)}** in the last year of watched Tupperbox roleplay, and I couldn't find a close name match.",
                ephemeral=True,
            )
            return

        key = closest[0]
        candidate = candidates[key]["character"]
        row = candidates[key]
        view = ConfirmCharacterView(interaction.user.id, interaction.guild.id, candidate, row)
        await interaction.followup.send(
            f"<@{interaction.user.id}>, I couldn't find **{discord.utils.escape_markdown(character)}** exactly. Did you mean **{discord.utils.escape_markdown(candidate)}**?",
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @bot.group.command(name="weekly", description="Read Calliope's latest Sunday weekly chronicle")
    async def weekly(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        if not is_admin(interaction):
            await interaction.response.send_message("Manage Server permission is required for the server-wide weekly chronicle.", ephemeral=True)
            return
        row = await bot.db.latest_weekly_summary(interaction.guild.id)
        if not row:
            await interaction.response.send_message("Calliope has not written a Sunday weekly chronicle yet.", ephemeral=True)
            return
        heading = f"**Sunday Weekly Chronicle — week ending {row['period_end'].date().isoformat()}**\n"
        text = heading + row["summary"]
        await interaction.response.send_message(text[:1990], ephemeral=True)

    @bot.group.command(name="summary", description="Read recent Calliope chronicle entries")
    async def summary(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        weekly_row = await bot.db.latest_weekly_summary(interaction.guild.id) if is_admin(interaction) else None
        rows = await bot.db.recent_summaries(interaction.guild.id, 5)
        if not weekly_row and not rows:
            await interaction.response.send_message("Calliope has not written a chronicle entry yet.", ephemeral=True)
            return
        parts: list[str] = []
        if weekly_row:
            parts.append(f"**Sunday Weekly Chronicle — week ending {weekly_row['period_end'].date().isoformat()}**\n{weekly_row['summary']}")
        if rows:
            recent = "\n\n".join(f"**<#{row['channel_id']}>**\n{row['summary']}" for row in reversed(rows))
            parts.append(f"**Recent Chronicle Entries**\n{recent}")
        text = "\n\n".join(parts)
        await interaction.response.send_message(text[:1990], ephemeral=True)
