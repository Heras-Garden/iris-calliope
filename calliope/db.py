from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

import aiosqlite

from .crypto import Cipher


SCHEMA = """
CREATE TABLE IF NOT EXISTS watched_channels (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    added_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS trusted_tupperbox_webhooks (
    guild_id INTEGER NOT NULL,
    webhook_id INTEGER NOT NULL,
    added_at INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (guild_id, webhook_id)
);

CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL UNIQUE,
    webhook_id INTEGER NOT NULL,
    character_name_enc BLOB NOT NULL,
    content_enc BLOB NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    summarized_at INTEGER
);

CREATE INDEX IF NOT EXISTS raw_messages_expiry_idx ON raw_messages (expires_at);
CREATE INDEX IF NOT EXISTS raw_messages_unsummarized_idx ON raw_messages (guild_id, channel_id, summarized_at);

CREATE TABLE IF NOT EXISTS known_characters (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    name_key TEXT NOT NULL,
    name_enc BLOB NOT NULL,
    PRIMARY KEY (guild_id, channel_id, name_key)
);

CREATE TABLE IF NOT EXISTS chronicle_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    period_start INTEGER NOT NULL,
    period_end INTEGER NOT NULL,
    summary_enc BLOB NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    week_key TEXT NOT NULL,
    period_start INTEGER NOT NULL,
    period_end INTEGER NOT NULL,
    summary_enc BLOB NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (guild_id, week_key)
);
"""


def _to_ts(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def _from_ts(value: int) -> datetime:
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _normalize_character_name(value: str) -> str:
    return " ".join(value.casefold().split())


class Database:
    def __init__(self, path: str, cipher: Cipher, retention_days: int = 7) -> None:
        self.path = path
        self.cipher = cipher
        self.retention_days = retention_days
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(SCHEMA)
        await self._backfill_known_characters()
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    def _conn(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("Database is not connected")
        return self.conn

    async def _backfill_known_characters(self) -> None:
        cursor = await self._conn().execute("SELECT guild_id, channel_id, character_name_enc FROM raw_messages")
        rows = await cursor.fetchall()
        for row in rows:
            name = self.cipher.decrypt(bytes(row["character_name_enc"]))
            normalized = _normalize_character_name(name)
            if not normalized:
                continue
            await self._conn().execute(
                "INSERT OR IGNORE INTO known_characters (guild_id, channel_id, name_key, name_enc) VALUES (?, ?, ?, ?)",
                (int(row["guild_id"]), int(row["channel_id"]), self.cipher.fingerprint(normalized), self.cipher.encrypt(name)),
            )

    async def add_channel(self, guild_id: int, channel_id: int) -> None:
        await self._conn().execute("INSERT OR IGNORE INTO watched_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
        await self._conn().commit()

    async def remove_channel(self, guild_id: int, channel_id: int) -> None:
        await self._conn().execute("DELETE FROM watched_channels WHERE guild_id=? AND channel_id=?", (guild_id, channel_id))
        await self._conn().commit()

    async def list_channels(self, guild_id: int) -> list[int]:
        cursor = await self._conn().execute("SELECT channel_id FROM watched_channels WHERE guild_id=? ORDER BY added_at", (guild_id,))
        rows = await cursor.fetchall()
        return [int(row["channel_id"]) for row in rows]

    async def is_watched(self, guild_id: int, channel_id: int) -> bool:
        cursor = await self._conn().execute("SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=? LIMIT 1", (guild_id, channel_id))
        return await cursor.fetchone() is not None

    async def trust_webhook(self, guild_id: int, webhook_id: int) -> None:
        await self._conn().execute("INSERT OR IGNORE INTO trusted_tupperbox_webhooks (guild_id, webhook_id) VALUES (?, ?)", (guild_id, webhook_id))
        await self._conn().commit()

    async def untrust_webhook(self, guild_id: int, webhook_id: int) -> None:
        await self._conn().execute("DELETE FROM trusted_tupperbox_webhooks WHERE guild_id=? AND webhook_id=?", (guild_id, webhook_id))
        await self._conn().commit()

    async def list_webhooks(self, guild_id: int) -> list[int]:
        cursor = await self._conn().execute("SELECT webhook_id FROM trusted_tupperbox_webhooks WHERE guild_id=? ORDER BY added_at", (guild_id,))
        rows = await cursor.fetchall()
        return [int(row["webhook_id"]) for row in rows]

    async def is_trusted_webhook(self, guild_id: int, webhook_id: int) -> bool:
        cursor = await self._conn().execute("SELECT 1 FROM trusted_tupperbox_webhooks WHERE guild_id=? AND webhook_id=? LIMIT 1", (guild_id, webhook_id))
        return await cursor.fetchone() is not None

    async def store_raw_message(self, guild_id: int, channel_id: int, message_id: int, webhook_id: int, character_name: str, content: str, created_at: datetime) -> None:
        expires_at = created_at + timedelta(days=self.retention_days)
        normalized_name = _normalize_character_name(character_name)
        await self._conn().execute(
            """
            INSERT OR IGNORE INTO raw_messages
            (guild_id, channel_id, message_id, webhook_id, character_name_enc, content_enc, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                message_id,
                webhook_id,
                self.cipher.encrypt(character_name),
                self.cipher.encrypt(content),
                _to_ts(created_at),
                _to_ts(expires_at),
            ),
        )
        if normalized_name:
            await self._conn().execute(
                "INSERT OR IGNORE INTO known_characters (guild_id, channel_id, name_key, name_enc) VALUES (?, ?, ?, ?)",
                (guild_id, channel_id, self.cipher.fingerprint(normalized_name), self.cipher.encrypt(character_name)),
            )
        await self._conn().commit()

    async def list_characters(self, guild_id: int, channel_ids: list[int]) -> list[str]:
        if not channel_ids:
            return []
        placeholders = ",".join("?" for _ in channel_ids)
        cursor = await self._conn().execute(
            f"SELECT name_enc FROM known_characters WHERE guild_id=? AND channel_id IN ({placeholders})",
            [guild_id, *channel_ids],
        )
        rows = await cursor.fetchall()
        names: dict[str, str] = {}
        for row in rows:
            name = self.cipher.decrypt(bytes(row["name_enc"]))
            key = _normalize_character_name(name)
            if key and key not in names:
                names[key] = name
        return sorted(names.values(), key=str.casefold)

    async def unsummarized_groups(self, min_messages: int) -> list[tuple[int, int]]:
        cursor = await self._conn().execute(
            """
            SELECT guild_id, channel_id
            FROM raw_messages
            WHERE summarized_at IS NULL AND expires_at > unixepoch()
            GROUP BY guild_id, channel_id
            HAVING COUNT(*) >= ?
            """,
            (min_messages,),
        )
        rows = await cursor.fetchall()
        return [(int(row["guild_id"]), int(row["channel_id"])) for row in rows]

    async def get_unsummarized(self, guild_id: int, channel_id: int) -> list[dict]:
        cursor = await self._conn().execute(
            """
            SELECT id, character_name_enc, content_enc, created_at
            FROM raw_messages
            WHERE guild_id=? AND channel_id=? AND summarized_at IS NULL AND expires_at > unixepoch()
            ORDER BY created_at
            """,
            (guild_id, channel_id),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": int(row["id"]),
                "character": self.cipher.decrypt(bytes(row["character_name_enc"])),
                "content": self.cipher.decrypt(bytes(row["content_enc"])),
                "created_at": _from_ts(row["created_at"]),
            }
            for row in rows
        ]

    async def save_summary(self, guild_id: int, channel_id: int, period_start: datetime, period_end: datetime, summary: str, raw_ids: Iterable[int]) -> None:
        ids = list(raw_ids)
        conn = self._conn()
        try:
            await conn.execute("BEGIN")
            await conn.execute(
                """
                INSERT INTO chronicle_summaries
                (guild_id, channel_id, period_start, period_end, summary_enc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, _to_ts(period_start), _to_ts(period_end), self.cipher.encrypt(summary)),
            )
            if ids:
                placeholders = ",".join("?" for _ in ids)
                await conn.execute(f"UPDATE raw_messages SET summarized_at=unixepoch() WHERE id IN ({placeholders})", ids)
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise

    async def summaries_between(self, guild_id: int, period_start: datetime, period_end: datetime) -> list[dict]:
        cursor = await self._conn().execute(
            """
            SELECT channel_id, period_start, period_end, summary_enc
            FROM chronicle_summaries
            WHERE guild_id=? AND period_end > ? AND period_end <= ?
            ORDER BY period_end
            """,
            (guild_id, _to_ts(period_start), _to_ts(period_end)),
        )
        rows = await cursor.fetchall()
        return [
            {
                "channel_id": int(row["channel_id"]),
                "period_start": _from_ts(row["period_start"]),
                "period_end": _from_ts(row["period_end"]),
                "summary": self.cipher.decrypt(bytes(row["summary_enc"])),
            }
            for row in rows
        ]

    async def weekly_summary_exists(self, guild_id: int, week_key: str) -> bool:
        cursor = await self._conn().execute("SELECT 1 FROM weekly_summaries WHERE guild_id=? AND week_key=? LIMIT 1", (guild_id, week_key))
        return await cursor.fetchone() is not None

    async def save_weekly_summary(self, guild_id: int, week_key: str, period_start: datetime, period_end: datetime, summary: str) -> None:
        await self._conn().execute(
            """
            INSERT OR IGNORE INTO weekly_summaries
            (guild_id, week_key, period_start, period_end, summary_enc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, week_key, _to_ts(period_start), _to_ts(period_end), self.cipher.encrypt(summary)),
        )
        await self._conn().commit()

    async def latest_weekly_summary(self, guild_id: int) -> dict | None:
        cursor = await self._conn().execute(
            """
            SELECT week_key, period_start, period_end, summary_enc
            FROM weekly_summaries
            WHERE guild_id=?
            ORDER BY period_end DESC
            LIMIT 1
            """,
            (guild_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "week_key": row["week_key"],
            "period_start": _from_ts(row["period_start"]),
            "period_end": _from_ts(row["period_end"]),
            "summary": self.cipher.decrypt(bytes(row["summary_enc"])),
        }

    async def recent_character_messages(self, guild_id: int, channel_ids: list[int]) -> list[dict]:
        if not channel_ids:
            return []
        placeholders = ",".join("?" for _ in channel_ids)
        cursor = await self._conn().execute(
            f"""
            SELECT channel_id, message_id, character_name_enc, content_enc, created_at
            FROM raw_messages
            WHERE guild_id=? AND channel_id IN ({placeholders}) AND expires_at > unixepoch()
            ORDER BY created_at DESC
            """,
            [guild_id, *channel_ids],
        )
        rows = await cursor.fetchall()
        return [
            {
                "channel_id": int(row["channel_id"]),
                "message_id": int(row["message_id"]),
                "character": self.cipher.decrypt(bytes(row["character_name_enc"])),
                "content": self.cipher.decrypt(bytes(row["content_enc"])),
                "created_at": _from_ts(row["created_at"]),
            }
            for row in rows
        ]

    async def recent_summaries(self, guild_id: int, limit: int = 10) -> list[dict]:
        cursor = await self._conn().execute(
            """
            SELECT channel_id, period_start, period_end, summary_enc
            FROM chronicle_summaries
            WHERE guild_id=?
            ORDER BY period_end DESC
            LIMIT ?
            """,
            (guild_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "channel_id": int(row["channel_id"]),
                "period_start": _from_ts(row["period_start"]),
                "period_end": _from_ts(row["period_end"]),
                "summary": self.cipher.decrypt(bytes(row["summary_enc"])),
            }
            for row in rows
        ]

    async def delete_expired(self) -> int:
        cursor = await self._conn().execute("DELETE FROM raw_messages WHERE expires_at <= unixepoch()")
        await self._conn().commit()
        return max(0, cursor.rowcount)

    async def delete_message(self, guild_id: int, message_id: int) -> int:
        cursor = await self._conn().execute("DELETE FROM raw_messages WHERE guild_id=? AND message_id=?", (guild_id, message_id))
        await self._conn().commit()
        return max(0, cursor.rowcount)

    async def delete_guild_data(self, guild_id: int) -> None:
        conn = self._conn()
        try:
            await conn.execute("BEGIN")
            for table in ("raw_messages", "known_characters", "chronicle_summaries", "weekly_summaries", "trusted_tupperbox_webhooks", "watched_channels"):
                await conn.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
