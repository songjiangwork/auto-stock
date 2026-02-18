# AGENTS.md

## Scope
This file defines project-level working rules for AI coding agents in this repository.

## Core Rules
1. After any code change, run unit tests before finalizing.
2. If behavior, commands, config, or workflow changes, update `README.md` when needed.
3. Never commit secrets (API keys, tokens, private credentials, real account identifiers).
4. Prefer minimal, focused changes; avoid unrelated refactors.
5. Keep CLI behavior backward compatible unless explicitly requested.

## Testing Policy
1. Default unit test command: `python -m pytest -q`
2. If no tests are discovered or pytest is unavailable, report that clearly in the response.
3. If tests fail, report failing cases and do not claim success.
4. If tests fail, first attempt to fix the code/tests and re-run tests before reporting back.
5. Continue attempting reasonable fixes in the current session until tests pass or a hard blocker is reached.

## Documentation Policy
1. Update docs for new commands, flags, config fields, outputs, or file paths.
2. Keep examples executable for Windows PowerShell where possible.

## Git Policy
1. Do not rewrite history unless explicitly requested.
2. Do not use destructive commands like `git reset --hard` without explicit user approval.
3. Keep commit messages clear and scoped.

## Collaboration Style
1. Be concise and pragmatic.
2. Show concrete command examples when helpful.
3. Highlight assumptions and risks early.
