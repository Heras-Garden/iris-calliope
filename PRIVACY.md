# Iris Calliope Privacy Policy

_Last updated: September 20, 2026_

Iris Calliope is a Discord roleplay narrative archivist operated as part of Hera's Garden. This document describes the data Calliope is designed to process and retain.

## What Calliope reads

Calliope only ingests message content when a message is:

- in a server where Calliope is installed;
- inside a channel that a server administrator explicitly added to Calliope's watch list; and
- sent through a webhook ID that the server administrator explicitly trusted as a Tupperbox source.

Calliope does not intentionally ingest ordinary user messages or unrelated bot messages.

The `/calliope suggest` command briefly checks recent channel history for webhook activity to help an administrator decide which channels may contain roleplay. That suggestion scan does not persist or summarize the scanned messages.

## What Calliope stores temporarily

For trusted Tupperbox RP messages, Calliope stores:

- Discord guild ID;
- Discord channel ID;
- Discord message ID;
- trusted webhook ID;
- proxy/character display name;
- message text;
- creation timestamp; and
- deletion/expiry timestamp.

Character names and message text are encrypted before they are written to PostgreSQL.

Raw roleplay text is retained for no more than **7 days**. Expired raw messages are deleted automatically whether or not summary generation succeeded.

When a member explicitly runs `/calliope find`, Calliope first searches this seven-day temporary store. If no exact character match is found, she may temporarily read older message history from watched channels in expanding windows (20, 30, 60, 90, 180, and up to 365 days). This older history search is restricted to trusted Tupperbox webhook messages and channels the requesting member can already view. Messages read during this fallback search are not inserted into Calliope's database or retained as a historical backfill.

## What Calliope stores long-term

Calliope may retain encrypted narrative summaries created from the temporary RP transcript. These summaries are designed to describe fictional events, characters, locations, and unresolved story threads rather than the behavior of the real people participating in the roleplay.

## What Calliope does not do

Calliope does not intentionally:

- map Tupperbox proxies back to Discord users;
- use Tupperbox `showuser` to identify proxy owners;
- rank or score users;
- create participation leaderboards;
- infer relationships between Discord users;
- build behavioral profiles;
- collect ordinary server conversation outside watched RP sources; or
- perform historical backfills of server message history.

## LLM processing

Calliope can send temporary RP text to the LLM endpoint configured by the operator for the sole purpose of producing narrative summaries. Calliope itself does not train or fine-tune models on Discord message content.

A deployment operator is responsible for choosing an LLM provider or self-hosted endpoint whose data handling is appropriate for the community and for disclosing any third-party processing that applies to that deployment.

## Encryption and security

Sensitive textual data stored by Calliope is encrypted at the application layer with a deployment-specific Fernet key before it is written to PostgreSQL. Discord credentials, database credentials, LLM API keys, and the encryption key must be supplied through deployment environment variables and must not be committed to the repository.

The deployment operator is also responsible for securing the Railway project, PostgreSQL service, backups, and access controls.

## Deletion controls

Server administrators can:

- stop collection in a channel with `/calliope channel remove`;
- delete a temporarily stored raw message by ID with `/calliope forget-message`; and
- erase Calliope's stored configuration, temporary messages, trusted webhook IDs, and summaries for the server with `/calliope erase-server-data`.

Because Calliope does not map Tupperbox proxies to Discord users, it does not maintain a Discord-user-linked RP profile. `/calliope my-data` and `/calliope delete-my-data` explain this behavior inside Discord.

## Changes

This policy should be updated whenever Calliope's collection, retention, storage, or LLM-processing behavior changes.
