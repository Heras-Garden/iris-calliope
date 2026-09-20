from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import asyncpg

from .crypto import Cipher


SCHEMA = """
CREATE TABLE IF NOT EXISTS watched_channels (
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS trusted_tupperbox_webhooks (
    guild_id BIGINT NOT NULL,
    webhook_id BIGINT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, webhook_id)
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL UNIQUE,
    webhook_id BIGINT NOT NULL,
    character_name_enc BYTEA NOT NULL,
    content_enc BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    summarized_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS raw_messages_expiry_idx ON raw_messages (expires_at);
CREATE INDEX IF NOT EXISTS raw_messages_unsummarized_idx ON raw_messages (guild_id, channel_id, summarized_at);

CREATE TABLE IF NOT EXISTS chronicle_summaries (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    summary_enc BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class Database:
    def __init__(self, url: str, cipher: Cipher, retention_days: int = 7) -> None:
        self.url = url
        self.cipher = cipher
        self.retention_days = retention_days
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5)
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Database is not connected")
        return self.pool

    async def add_channel(self, guild_id: int, channel_id: int) -> None:
        await self._pool().execute("INSERT INTO watched_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", guild_id, channel_id)

    async def remove_channel(self, guild_id: int, channel_id: int) -> None:
        await self._pool().execute("DELETE FROM watched_channels WHERE guild_id=$1 AND channel_id=$2", guild_id, channel_id)

    async def list_channels(self, guild_id: int) -> list[int]:
        rows = await self._pool().fetch("SELECT channel_id FROM watched_channels WHERE guild_id=$1 ORDER BY added_at", guild_id)
        return [int(row["channel_id"]) for row in rows]

    async def is_watched(self, guild_id: int, channel_id: int) -> bool:
        return bool(await self._pool().fetchval("SELECT 1 FROM watched_channels WHERE guild_id=$1 AND channel_id=$2", guild_id, channel_id))

    async def trust_webhook(self, guild_id: int, webhook_id: int) -> None:
        await self._pool().execute("INSERT INTO trusted_tupperbox_webhooks (guild_id, webhook_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", guild_id, webhook_id)

    async def untrust_webhook(self, guild_id: int, webhook_id: int) -> None:
        await self._pool().execute("DELETE FROM trusted_tupperbox_webhooks WHERE guild_id=$1 AND webhook_id=$2", guild_id, webhook_id)

    async def list_webhooks(self, guild_id: int) -> list[int]:
        rows = await self._pool().fetch("SELECT webhook_id FROM trusted_tupperbox_webhooks WHERE guild_id=$1 ORDER BY added_at", guild_id)
        return [int(row["webhook_id"]) for row in rows]

    async def is_trusted_webhook(self, guild_id: int, webhook_id: int) -> bool:
        return bool(await self._pool().fetchval("SELECT 1 FROM trusted_tupperbox_webhooks WHERE guild_id=$1 AND webhook_id=$2", guild_id, webhook_id))

    async def store_raw_message(self, guild_id: int, channel_id: int, message_id: int, webhook_id: int, character_name: str, content: str, created_at: datetime) -> None:
        expires_at = created_at + timedelta(days=self.retention_days)
        await self._pool().execute("""
            INSERT INTO raw_messages (guild_id, channel_id, message_id, webhook_id, character_name_enc, content_enc, created_at, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (message_id) DO NOTHING
            """, guild_id, channel_id, message_id, webhook_id, self.cipher.encrypt(character_name), self.cipher.encrypt(content), created_at, expires_at)

    async def unsummarized_groups(self, min_messages: int) -> list[tuple[int, int]]:
        rows = await self._pool().fetch("""
            SELECT guild_id, channel_id FROM raw_messages
            WHERE summarized_at IS NULL AND expires_at > NOW()
            GROUP BY guild_id, channel_id
            HAVING COUNT(*) >= $1
            """, min_messages)
        return [(int(r["guild_id"]), int(r["channel_id"])) for r in rows]

    async def get_unsummarized(self, guild_id: int, channel_id: int) -> list[dict]:
        rows = await self._pool().fetch("""
            SELECT id, character_name_enc, content_enc, created_at FROM raw_messages
            WHERE guild_id=$1 AND channel_id=$2 AND summarized_at IS NULL AND expires_at > NOW()
            ORDER BY created_at
            """, guild_id, channel_id)
        return [{"id": int(r["id"]), "character": self.cipher.decrypt(bytes(r["character_name_enc"])), "content": self.cipher.decrypt(bytes(r["content_enc"])), "created_at": r["created_at"]} for r in rows]

    async def save_summary(self, guild_id: int, channel_id: int, period_start: datetime, period_end: datetime, summary: str, raw_ids: Iterable[int]) -> None:
        ids = list(raw_ids)
        async with self._pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO chronicle_summaries (guild_id, channel_id, period_start, period_end, summary_enc)
                    VALUES ($1,$2,$3,$4,$5)
                    """, guild_id, channel_id, period_start, period_end, self.cipher.encrypt(summary))
                if ids:
                    await conn.execute("UPDATE raw_messages SET summarized_at=NOW() WHERE id = ANY($1::bigint[])", ids)

    async def recent_summaries(self, guild_id: int, limit: int = 10) -> list[dict]:
        rows = await self._pool().fetch("""
            SELECT channel_id, period_start, period_end, summary_enc FROM chronicle_summaries
            WHERE guild_id=$1 ORDER BY period_end DESC LIMIT $2
            """, guild_id, limit)
        return [{"channel_id": int(r["channel_id"]), "period_start": r["period_start"], "period_end": r["period_end"], "summary": self.cipher.decrypt(bytes(r["summary_enc"]))} for r in rows]

    async def delete_expired(self) -> int:
        result = await self._pool().execute("DELETE FROM raw_messages WHERE expires_at <= NOW()")
        return int(result.split()[-1])

    async def delete_message(self, guild_id: int, message_id: int) -> int:
        result = await self._pool().execute("DELETE FROM raw_messages WHERE guild_id=$1 AND message_id=$2", guild_id, message_id)
        return int(result.split()[-1])

    async def delete_guild_data(self, guild_id: int) -> None:
        async with self._pool().acquire() as conn:
            async with conn.transaction():
                for table in ("raw_messages", "chronicle_summaries", "trusted_tupperbox_webhooks", "watched_channels"):
                    await conn.execute(f"DELETE FROM {table} WHERE guild_id=$1", guild_id)
