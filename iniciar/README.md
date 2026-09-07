# Conversation checkpoint

This folder holds the persistent state of an ongoing working session between
the user and the assistant. It is intended to let the conversation resume from
the last known good point after a crash, reboot, or restart of the assistant.

## What is stored

- `session.json` — machine-readable checkpoint with:
  - session id and created/updated timestamps
  - project context summary (what the repo is, what we were working on)
  - the last known topic and the next question to ask the user
  - notes about decisions already made
- Optional transcript files (markdown) if the session grows large; these are
  human-readable and can be used to reconstruct earlier turns.

## How to resume

After a restart, load `session.json`, read the project context and the last
topic, then continue the work from the recorded next step. Update the
`updated_at` field and the "last topic" whenever the conversation meaningfully
changes direction.

## Conventions

- One session file per active conversation thread.
- Keep the checkpoint small and durable; prefer appending transcripts over
  mutating the whole file on every message if the session gets long.
- Treat `session.json` as the source of truth for "where we are right now".
