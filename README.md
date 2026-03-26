# hindclaw-claude-plugin

Claude Code hooks plugin for [Hindsight](https://hindsight.vectorize.io) memory with JWT auth via [HindClaw](https://hindclaw.pro) server extensions.

## What it does

Adds long-term memory to Claude Code sessions. The plugin signs JWTs per-request and connects to an existing Hindsight server running hindclaw extensions. All access control, permission resolution, and tag enrichment happen server-side.

- **Recall** — before every prompt, fetches relevant memories from Hindsight
- **Retain** — after every Nth response, stores conversation chunks for fact extraction
- **Session lifecycle** — health check on start, state cleanup on end

## Requirements

- Python 3.11+ (stdlib only — zero external dependencies)
- A Hindsight server with [hindclaw-extension](https://pypi.org/project/hindclaw-extension/) installed
- A user channel mapping for `claude-code` provider (via Terraform)

## Installation

```bash
# Install via Claude Code plugin marketplace
claude plugin marketplace add mrkhachaturov/ccode-personal-plugins
claude plugin install hindclaw-claude-plugin
```

## Configuration

### Global config (`~/.claude/hindclaw.json`)

```json
{
    "hindsightApiUrl": "https://hindsight.example.com",
    "jwtSecret": "your-shared-secret",
    "userId": "you@example.com"
}
```

### Per-project override (`.claude/hindclaw.json`)

```json
{
    "agentName": "my-project",
    "recallBudget": "high",
    "retainEveryNTurns": 5
}
```

### Environment variables (highest priority)

| Variable | Maps to |
|----------|---------|
| `HINDCLAW_API_URL` | `hindsightApiUrl` |
| `HINDCLAW_USER_ID` | `userId` |
| `HINDCLAW_JWT_SECRET` | `jwtSecret` |

### Config layer priority

1. Environment variables (host-wide)
2. Project config (`.claude/hindclaw.json` in project root)
3. User config (`~/.claude/hindclaw.json`)
4. Plugin defaults (`settings.json`)

### All settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hindsightApiUrl` | string | required | Hindsight server URL |
| `jwtSecret` | string | required | HMAC-SHA256 shared secret |
| `userId` | string | auto | User identity (auto-detected from `git config user.email`) |
| `clientId` | string | `"claude-code"` | JWT client_id claim |
| `bankIdPrefix` | string | auto | Prefix for bank IDs (auto-derived from email) |
| `agentName` | string | auto | Project name (auto-derived from git remote or folder) |
| `bankId` | string | auto | Explicit bank ID override |
| `autoRecall` | bool | `true` | Enable automatic recall |
| `autoRetain` | bool | `true` | Enable automatic retain |
| `recallBudget` | string | `"mid"` | Recall effort: `low`, `mid`, `high` |
| `recallMaxTokens` | int | `1024` | Max tokens for recalled memories |
| `recallTypes` | list | `["world", "experience"]` | Memory types to recall |
| `recallContextTurns` | int | `1` | User turns to include in recall query |
| `recallMaxQueryChars` | int | `800` | Max characters for recall query |
| `recallTopK` | int | `null` | Hard cap on memories returned |
| `retainRoles` | list | `["user", "assistant"]` | Roles to include in retained conversation |
| `retainEveryNTurns` | int | `10` | Retain every Nth turn |
| `retainOverlapTurns` | int | `2` | Overlap turns for continuity |
| `retainContext` | string | `"claude-code"` | Context label for retained facts |
| `debug` | bool | `false` | Enable debug logging to stderr |

## Bank ID derivation

When `bankId` is not explicitly set, it is derived automatically:

```
{bankIdPrefix}::{agentName}

bankIdPrefix: userId with @ and . replaced by _ (e.g. ceo@example.com → ceo_example_com)
agentName:    git remote repo name → folder basename fallback
result:       ceo_example_com::my-project
```

## How it works

```
User message → UserPromptSubmit hook → recall.py
  → Signs JWT (sender: "claude-code:{email}")
  → POST /v1/default/banks/{bankId}/memories/recall
  → Server: HindclawTenant decodes JWT → resolves user → HindclawValidator checks permissions
  → Formats memories → injects as additionalContext

Claude responds → Stop hook → retain.py
  → Reads JSONL transcript, applies turn counting + sliding window
  → Signs JWT → POST /v1/default/banks/{bankId}/memories
  → Server extracts facts per bank's retain_mission
```

## Terraform prerequisites

Each developer needs a user + channel mapping:

```hcl
resource "hindclaw_user_channel" "dev_claude_code" {
  user_id          = hindclaw_user.dev.id
  channel_provider = "claude-code"
  sender_id        = "dev@example.com"
}
```

## Testing

```bash
python -m pytest tests/ -v
```

## License

MIT
