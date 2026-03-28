# CLAUDE.md — hindclaw-claude-plugin

## What this is

Claude Code hooks plugin for long-term memory via Hindsight + HindClaw. Pure Python 3.11+ stdlib, zero external dependencies.

## Repository structure

```
scripts/              # Hook entrypoints (4 scripts)
scripts/lib/          # Shared modules (client, config, state, content)
tests/                # pytest suite (189 tests)
hooks/hooks.json      # Hook event definitions
settings.json         # Plugin defaults
.claude-plugin/       # Plugin manifest
```

## Commands

```bash
# Run tests
/usr/bin/python3.12 -m pytest tests/ -v

# Run a single test file
/usr/bin/python3.12 -m pytest tests/test_client.py -v

# Run a specific test
/usr/bin/python3.12 -m pytest tests/test_hooks.py::TestRecallHook::test_memories_found -v
```

## How to make changes

### Adding a config key

1. Add the key with its default value to `settings.json`
2. Read it in the relevant hook script via `config.get("keyName", default)`
3. Add test coverage in `tests/test_config.py` (layer priority) and `tests/test_hooks.py` (behavior)
4. Document it in `README.md` config tables
5. If it changes behavior, add a CHANGELOG entry

### Changing hook behavior

1. Edit the hook script in `scripts/`
2. Update or add integration tests in `tests/test_hooks.py` (uses importlib + mocked stdin/stdout/HTTP)
3. Run the full suite: `/usr/bin/python3.12 -m pytest tests/ -v`

### Changing the client (API calls)

1. Edit `scripts/lib/client.py`
2. Update `tests/test_client.py`
3. If adding a new API method, add it to `HindclawClient` and test both success and error paths

### Changing state shape

1. Update `_default_state()` in `scripts/lib/state.py`
2. If adding a flag, add it to `_VALID_FLAGS`
3. Update the initial state dict in `scripts/session_start.py` to match
4. Update `tests/test_state.py` and `tests/test_hooks.py`

## Architecture notes

- **Hooks are ephemeral processes.** Each hook invocation is a fresh Python process. State must be persisted to files.
- **State uses `fcntl.flock`** for cross-process locking. The `set_flag()` and `increment_turn()` functions handle this.
- **Content processing (`content.py`) is stable.** It handles transcript parsing, memory formatting, channel envelope stripping. Changes here are rare.
- **The client is thin.** `HindclawClient(api_url, api_key)` with a static Bearer header. Three API methods: `recall`, `retain`, `create_bank`. All heavy logic is server-side.

## Style

- No external dependencies. Everything uses Python stdlib.
- Google-style docstrings with `Args:`, `Returns:`, `Raises:`.
- `str | None` syntax, not `Optional[str]`.
- Tests use `unittest.TestCase` with `unittest.mock.patch`.

## Releasing a new version

1. Update version in `.claude-plugin/plugin.json`
2. Add changelog entry to `CHANGELOG.md` following the existing format
3. Commit: `release(claude-plugin): v0.X.Y`
4. Tag: `claude-plugin-v0.X.Y`
5. Push commit + tag

## Commit style

Conventional commits: `feat(claude-plugin):`, `fix(claude-plugin):`, `refactor(claude-plugin):`, `test(claude-plugin):`, `docs(claude-plugin):`, `chore(claude-plugin):`, `release(claude-plugin):`
