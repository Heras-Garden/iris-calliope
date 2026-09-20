from __future__ import annotations

import discord

from .commands_core import is_admin


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
        await interaction.response.send_message(f"Trusted webhook `{message.webhook_id}`. Only trusted webhook sources can enter Calliope's archive.", ephemeral=True)

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
        await interaction.response.send_message("\n".join(f"• `{i}`" for i in ids) if ids else "No trusted webhook IDs.", ephemeral=True)

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
