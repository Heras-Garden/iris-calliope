from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    discord_token: str
    database_path: str
    encryption_key: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    summary_interval_hours: int
    summary_min_messages: int
    suggest_history_limit: int
    raw_retention_days: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            discord_token=_required("DISCORD_TOKEN"),
            database_path=os.getenv("CALLIOPE_DB_PATH", "/data/calliope.db").strip() or "/data/calliope.db",
            encryption_key=_required("CALLIOPE_ENCRYPTION_KEY"),
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip().rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            summary_interval_hours=max(1, int(os.getenv("SUMMARY_INTERVAL_HOURS", "6"))),
            summary_min_messages=max(1, int(os.getenv("SUMMARY_MIN_MESSAGES", "3"))),
            suggest_history_limit=min(100, max(1, int(os.getenv("SUGGEST_HISTORY_LIMIT", "50")))),
        )

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)
