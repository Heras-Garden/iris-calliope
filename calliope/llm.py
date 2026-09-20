from __future__ import annotations

import httpx

from .config import Settings


SYSTEM_PROMPT = """You are Iris Calliope, a neutral narrative archivist for collaborative roleplay. Summarize only the fictional events in the supplied Tupperbox roleplay transcript. Do not rank, score, profile, infer, or identify the real people behind characters. Do not infer real-world relationships between Discord users. Preserve important fictional events, locations, named characters, and unresolved story threads. Write a concise chronicle entry in third person."""

WEEKLY_SYSTEM_PROMPT = """You are Iris Calliope, a neutral narrative archivist for collaborative roleplay. Create one concise weekly chronicle from the supplied channel chronicle entries. Combine overlapping events, preserve important named characters, locations, major developments, and unresolved fictional story threads, and do not invent events that are not present. Do not rank, score, profile, infer, or identify the real people behind characters. Do not infer real-world relationships between Discord users."""


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _complete(self, system_prompt: str, content: str) -> str:
        if not self.settings.llm_enabled:
            raise RuntimeError("LLM is not configured")

        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()

    async def summarize(self, transcript: str) -> str:
        return await self._complete(SYSTEM_PROMPT, transcript)

    async def summarize_week(self, chronicle_entries: str) -> str:
        return await self._complete(WEEKLY_SYSTEM_PROMPT, chronicle_entries)
