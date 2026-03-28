# Changelog

## [0.2.0] - 2026-03-28

Complete rewrite of authentication and configuration. Migrates from JWT signing to API key auth, simplifies config to explicit values with no auto-derivation, and adds bank creation from template.

### Changed

- **Auth: JWT → API key.** Plugin sends `Authorization: Bearer {api_key}` on every request. No more JWT signing, no shared secrets, no claims construction. Server resolves identity and permissions from the key.
- **Config: 3 layers + env overrides.** Plugin defaults → user config (`~/.claude/hindclaw.json`) → project config (`.claude/hindclaw.json`). Env vars `HINDCLAW_API_URL` and `HINDCLAW_API_KEY` override everything. No auto-derivation of bank IDs from git email or folder names.
- **State: simplified flags.** Replaced `denied_banks` list with boolean flags: `error_notified`, `config_warned`, `bank_created`. Single `healthy` flag — once false, stays false for the session.
- **Error notifications.** Errors output `systemMessage` (user sees in terminal) and `additionalContext` (Claude sees in context). One-time notifications — fatal errors notify once, then go silent.
- **Recall: warnings handling.** If server caps recall budget or max tokens (policy enforcement), plugin shows a one-time `systemMessage` warning. Memory still works with capped values.
- **Retain: bank creation from template.** On 404 (bank not found), plugin creates the bank from a configured template via `POST /ext/hindclaw/banks`. Handles 201, 403, 404, 409, 422.

### Added

- `apiKey` config key (required) — SA key (`hc_sa_*`) or user key (`hc_u_*`)
- `bankId` config key (required) — explicit project bank ID
- `template` config key (optional) — template name for auto-creating banks
- `create_bank()` method on `HindclawClient`
- `set_flag()` and `mark_unhealthy()` state helpers with `fcntl` locking
- Flag validation in `set_flag()` to catch typos

### Removed

- `scripts/lib/auth.py` — JWT signing module
- `tests/test_auth.py` — JWT tests
- Config keys: `jwtSecret`, `clientId`, `userId`, `agentName`, `bankIdPrefix`, `bankGranularity`, `strategy`, `scope`, `recallTypes`, `recallRoles`, `recallPromptPreamble`
- `add_denied_bank()` and `is_bank_denied()` state functions
- Git subprocess calls for auto-resolving user identity and project name

## [0.1.0] - 2026-03-23

Initial release. JWT-authenticated Claude Code hooks for Hindsight memory via HindClaw server extensions.

### Added

- Four Claude Code hooks: SessionStart (health check), UserPromptSubmit (recall), Stop (retain), SessionEnd (cleanup)
- JWT HMAC-SHA256 signing per request with sender/channel/topic/agent claims
- 4-layer config: env vars → project → user → plugin defaults
- Auto-derivation of userId (git email), agentName (git remote), bankId (prefix::agent)
- Chunked retention with sliding window (retainEveryNTurns + overlap)
- Multi-turn recall query composition with context truncation
- Channel message support (Telegram/Discord envelope stripping)
- Memory tag stripping to prevent feedback loops
- Per-session file-based state with fcntl locking
- 213 tests, zero external dependencies (pure Python 3.11+ stdlib)
