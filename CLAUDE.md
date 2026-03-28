# CLAUDE.md — hindclaw-claude-plugin

## Package

Claude Code integration plugin for Hindclaw.

## Project

This package contains the Claude-side integration logic, hook scripts, config handling, and tests
for connecting Claude Code workflows to Hindclaw.

## Structure

```
scripts/          # Hook entrypoints (recall, retain, session_start, session_end)
tests/            # Python test suite
hooks/            # Hook configuration
README.md
CLAUDE.md
```

## Commands

Test: `/usr/bin/python3.12 -m pytest tests/ -v`

Use the repository's own documented test and release workflow. Prefer updating this repo directly
like a normal standalone package repository.

## Publishing

Update the package version and `CHANGELOG.md`, commit, tag, and publish from this repository.
