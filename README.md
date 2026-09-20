# Iris Calliope

**Iris Calliope** is Hera's Garden's narrative archivist for collaborative Discord roleplay.

Calliope is designed to read only **Tupperbox-proxied roleplay messages** in channels that a server administrator explicitly chooses. She stays silent in watched roleplay channels, temporarily retains encrypted raw RP text for up to seven days, creates narrative summaries through a configurable LLM endpoint, and then deletes the raw text. Long-term storage contains Calliope's own encrypted summaries plus an encrypted fictional-character name registry rather than full transcripts.

## Privacy-first design

Calliope is intentionally story-centric rather than user-centric:

- No player rankings, participation scores, or activity leaderboards.
- No attempts to identify the Discord account behind a Tupperbox proxy.
- No relationship maps or user profiling.
- No server-wide passive message collection.
- No historical backfill feature.
- No ordinary user-message ingestion.
- Raw Tupperbox RP text expires after 7 days even if summary generation fails.
- Message content, character names, and generated summaries are encrypted at the application layer before SQLite storage.\n- Calliope keeps an encrypted name-only character registry so she can list fictional characters she has observed without linking them to Discord users.

See [PRIVACY.md](PRIVACY.md) for the full data-handling model.

## Commands

All Calliope slash-command responses are ephemeral, so she does not speak into the roleplay channels she watches.

### Channel controls

- `/calliope channel add` — add a roleplay channel to the watch list.
- `/calliope channel remove` — stop watching a channel.
- `/calliope channel list` — list watched channels.
- `/calliope suggest` — briefly scan recent channel history for webhook activity and suggest possible RP channels. The scan is not stored or summarized.

### Tupperbox source controls

Calliope uses a strict webhook allowlist so unrelated webhooks never enter the archive.

- `/calliope source trust-message` — point Calliope at a known Tupperbox proxy message; Calliope trusts that message's webhook ID.
- `/calliope source remove` — remove a trusted webhook ID.
- `/calliope source list` — list trusted webhook IDs.

### Story and privacy controls

- `/calliope info` — show watched channels, retention behavior, source restrictions, and LLM status.
- `/calliope summary` — privately read recent chronicle entries; administrators also see the latest Sunday weekly chronicle when one exists.\n- `/calliope weekly` — admin-only view of the latest server-wide Sunday weekly chronicle.\n- `/calliope characters` — privately list character names Calliope has learned from watched Tupperbox RP in channels the requester can view.
- `/calliope find character:<name>` — privately locate a character's most recent message. Calliope checks her 7-day temporary store first, then searches older watched Tupperbox history on demand in expanding windows up to one year. Older history is not saved back into SQLite.
- `/calliope privacy` — explain Calliope's data model.
- `/calliope my-data` — explain what Calliope stores about the requesting Discord account.
- `/calliope delete-my-data` — request deletion of account-linked data; in the current model there is no Discord-user-linked RP profile.
- `/calliope forget-message` — admin-only deletion of a temporarily stored raw RP message by Discord message ID.
- `/calliope erase-server-data` — admin-only deletion of all Calliope data for the server.

## How message ingestion works

A message enters Calliope's temporary RP store only when all of these are true:

1. It is in a Discord server.
2. The channel has been explicitly added to Calliope's watch list.
3. The message was sent through a webhook.
4. The webhook ID has been explicitly trusted as a Tupperbox source.
5. The message has text content.

Calliope does not use Tupperbox `showuser` or otherwise attempt to connect proxy characters to Discord accounts. The character registry stores fictional display names only. Existing retained messages are used to seed the registry after this feature is deployed; older Discord history is not persistently backfilled.

## LLM integration

Calliope expects an OpenAI-compatible `/chat/completions` endpoint so a self-hosted or custom model can be used.

Required when summary generation is enabled:

- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY` if your endpoint requires one\n\nEvery Sunday, Calliope can combine the prior week's already-generated chronicle entries into one encrypted weekly chronicle. The default generation boundary is 23:00 UTC and can be changed with `SUNDAY_SUMMARY_HOUR_UTC`.

The system prompt explicitly tells the model to summarize fictional events only and not identify, rank, score, or profile the real people behind characters.

Calliope itself does not train or fine-tune a model on Discord message content. Operators should only configure an LLM endpoint whose own data-handling terms are appropriate for the server.

## Railway deployment with a volume

Calliope uses SQLite and is designed to keep that database on a Railway persistent volume.

### 1. Attach a volume

Attach one volume to the `iris-calliope` service and mount it at:

```text
/data
```

Calliope stores the database at:

```text
/data/calliope.db
```

Set:

```text
CALLIOPE_DB_PATH=/data/calliope.db\nSUNDAY_SUMMARY_HOUR_UTC=23
```

There is no `DATABASE_URL` and no PostgreSQL service required.

Because SQLite is a single-file database, run **one Calliope service replica** against this volume rather than multiple replicas sharing the same file.

### 2. Configure environment variables

Copy the values from `.env.example` into Railway variables.

Generate a Fernet encryption key locally with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store that value as `CALLIOPE_ENCRYPTION_KEY`. Do not rotate it without first planning a data migration, because existing encrypted summaries require the same key to decrypt.

### 3. Discord application settings

Calliope needs:

- `View Channels`
- `Read Message History`
- the Message Content privileged intent

She does **not** need the Server Members privileged intent for this design.

Grant `Manage Server` only to the human administrators who should configure Calliope; the bot itself does not require Discord's `Manage Server` permission.

### 4. Start command

Railway can use the included `Procfile`:

```text
worker: python -m calliope
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
python -m calliope
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. For local development you can set `CALLIOPE_DB_PATH=./calliope.db` instead of using `/data`.

## Current scope

This first rework intentionally focuses on the safe foundation:

- watched-channel configuration
- one-time RP-channel suggestions
- trusted Tupperbox webhook ingestion
- encrypted SQLite storage on a persistent volume
- seven-day raw-message retention
- periodic LLM summaries
- persistent encrypted chronicle summaries
- privacy and deletion controls
- permission-aware character lookup with temporary older-history fallback\n- encrypted name-only character registry and `/calliope characters`\n- encrypted Sunday weekly chronicles built from existing channel summaries

Scene segmentation, richer chapter formatting, character/location indexes, and lore browsing can be layered on later without bringing back user analytics.
