# hindclaw-claude-plugin

Claude Code hooks plugin for [Hindsight](https://hindsight.vectorize.io) memory via [HindClaw](https://hindclaw.pro) server extensions.

## What it does

Adds long-term memory to Claude Code sessions. The plugin authenticates with an API key and connects to an existing Hindsight server running hindclaw extensions. All access control, permission resolution, and tag enrichment happen server-side.

- **Recall** — before every prompt, fetches relevant memories from Hindsight
- **Retain** — after every Nth response, stores conversation chunks for fact extraction
- **Session lifecycle** — health check on start, state cleanup on end

## Requirements

- Python 3.11+ (stdlib only — zero external dependencies)
- A Hindsight server with [hindclaw-extension](https://pypi.org/project/hindclaw-extension/) installed

## Installation

```bash
# Install via Claude Code plugin marketplace
claude plugin marketplace add mrkhachaturov/ccode-personal-plugins
claude plugin install hindclaw-claude-plugin
```

## Authentication

The plugin uses API keys. Two key types are supported:

- **SA keys** (`hc_sa_*`) — service account keys, recommended. Create an SA scoped to a specific bank and generate its key.
- **User keys** (`hc_u_*`) — personal keys tied to your user account.

Create an SA and generate a key via the CLI:

```bash
hindclaw sa create my-claude-agent --bank my-bank
hindclaw sa keys create my-claude-agent
```

## Configuration

### Global config (`~/.claude/hindclaw.json`)

```json
{
    "hindsightApiUrl": "https://hindsight.example.com",
    "apiKey": "hc_sa_...",
    "bankId": "my-bank"
}
```

### Per-project override (`.claude/hindclaw.json`)

```json
{
    "bankId": "project-specific-bank",
    "retainEveryNTurns": 5
}
```

### Environment variables (highest priority)

| Variable | Maps to |
|----------|---------|
| `HINDCLAW_API_URL` | `hindsightApiUrl` |
| `HINDCLAW_API_KEY` | `apiKey` |

### Config layer priority

1. Environment variables (host-wide)
2. Project config (`.claude/hindclaw.json` in project root)
3. User config (`~/.claude/hindclaw.json`)
4. Plugin defaults (`settings.json`)

### All settings

**Required**

| Field | Type | Description |
|-------|------|-------------|
| `hindsightApiUrl` | string | Hindsight server URL |
| `apiKey` | string | SA key (`hc_sa_*`) or user key (`hc_u_*`) |
| `bankId` | string | Target memory bank ID |

**Recall (optional)**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `autoRecall` | bool | `true` | Enable automatic recall |
| `recallBudget` | string | `"mid"` | Recall effort: `low`, `mid`, `high` |
| `recallMaxTokens` | int | `1024` | Max tokens for recalled memories |
| `recallContextTurns` | int | `1` | User turns to include in recall query |
| `recallMaxQueryChars` | int | `800` | Max characters for recall query |
| `recallTopK` | int | `null` | Hard cap on memories returned |

**Retain (optional)**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `autoRetain` | bool | `true` | Enable automatic retain |
| `retainEveryNTurns` | int | `10` | Retain every Nth turn |
| `retainOverlapTurns` | int | `2` | Overlap turns for continuity |
| `retainRoles` | list | `["user", "assistant"]` | Roles included in retained conversation |
| `retainContext` | string | `"claude-code"` | Context label for retained facts |

**Other (optional)**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `template` | string | `null` | Bank template name for auto-creation |
| `debug` | bool | `false` | Enable debug logging to stderr |

## Bank creation from template

If `template` is set and the bank does not exist, the plugin creates it from that template on the first retain. Templates are managed server-side via Terraform, the CLI, or the Hindsight API.

```json
{
    "bankId": "dev-personal",
    "template": "personal-dev"
}
```

The bank is created once. Subsequent retains skip the creation step.

## How it works

```
User message → UserPromptSubmit hook → recall.py
  → POST /v1/default/banks/{bankId}/memories/recall  (Bearer hc_sa_...)
  → Server: HindclawTenant validates key → HindclawValidator checks permissions
  → Formats memories → injects as additionalContext

Claude responds → Stop hook → retain.py
  → Reads JSONL transcript, applies turn counting + sliding window
  → POST /v1/default/banks/{bankId}/memories
  → Server extracts facts per bank's retain_mission
```

## Error handling

Errors are surfaced as Claude Code notifications:

- **`systemMessage`** — shown in the terminal. Used for fatal errors (misconfigured URL, auth failure, bank not found).
- **`additionalContext`** — injected into Claude's context for non-fatal issues Claude should know about (budget cap reached, token limit hit).

Fatal errors produce a one-time notification at the start of the session and suppress further recall/retain until the session is restarted. Budget and token cap warnings appear inline when a limit is hit.

## Testing

```bash
python -m pytest tests/ -v
```

## License

MIT
