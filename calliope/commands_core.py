from __future__ import annotations

import discord


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.guild and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild)


def register_core(bot) -> None:
    @bot.group.command(name="info", description="Show Calliope's watched channels and privacy behavior")
    async def info(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        ids = await bot.db.list_channels(interaction.guild.id)
        watched = ", ".join(f"<#{i}>" for i in ids) if ids else "No channels."
        llm = "configured" if bot.settings.llm_enabled else "not configured"
        await interaction.response.send_message(f"**Iris Calliope**\nWatching: {watched}\nSource: trusted Tupperbox webhooks only.\nRaw RP retention: 7 days, then deletion.\nLong-term memory: encrypted summaries only.\nLLM: {llm}. No user rankings, proxy-owner mapping, or user relationship profiling.", ephemeral=True)

    @bot.group.command(name="privacy", description="Explain Calliope's data handling")
    async def privacy(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Calliope stores only trusted Tupperbox RP from explicitly watched channels. Raw RP is encrypted and kept for at most 7 days. Long-term storage contains encrypted narrative summaries only. Calliope does not resolve proxy owners, rank users, or ingest ordinary user messages. See PRIVACY.md for details.", ephemeral=True)

    @bot.group.command(name="my-data", description="Explain what Calliope stores about your Discord account")
    async def my_data(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Calliope does not create Discord-user profiles or map Tupperbox proxies back to Discord accounts, so there is no user-linked RP record for your account to display.", ephemeral=True)

    @bot.group.command(name="delete-my-data", description="Request deletion of data linked to your Discord account")
    async def delete_my_data(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Calliope does not keep a Discord-user-linked RP profile. If a temporary proxy message needs removal before its 7-day expiry, a server admin can use `/calliope forget-message` with its message ID.", ephemeral=True)

    @bot.group.command(name="forget-message", description="Delete a temporarily stored RP message")
    async def forget_message(interaction: discord.Interaction, message_id: str) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        try:
            deleted = await bot.db.delete_message(interaction.guild.id, int(message_id))
        except ValueError:
            await interaction.response.send_message("Message ID must be numeric.", ephemeral=True)
            return
        await interaction.response.send_message("Stored raw message deleted." if deleted else "Calliope did not have that raw message stored.", ephemeral=True)

    @bot.group.command(name="erase-server-data", description="Delete all Calliope data for this server")
    async def erase_server_data(interaction: discord.Interaction) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        await bot.db.delete_guild_data(interaction.guild.id)
        await interaction.response.send_message("Calliope's stored data for this server has been erased.", ephemeral=True)

    @bot.channels.command(name="add", description="Add a roleplay channel for Calliope to watch")
    async def channel_add(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        await bot.db.add_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"Now watching {channel.mention}. Calliope will remain silent there.", ephemeral=True)

    @bot.channels.command(name="remove", description="Stop watching a roleplay channel")
    async def channel_remove(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not is_admin(interaction) or not interaction.guild:
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        await bot.db.remove_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"Stopped watching {channel.mention}.", ephemeral=True)

    @bot.channels.command(name="list", description="List channels Calliope watches")
    async def channel_list(interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command is only available in a server.", ephemeral=True)
            return
        ids = await bot.db.list_channels(interaction.guild.id)
        await interaction.response.send_message("\n".join(f"• <#{i}>" for i in ids) if ids else "No watched channels.", ephemeral=True)
