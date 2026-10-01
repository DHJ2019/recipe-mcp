# Recipe MCP — agent guide

This file and `CLAUDE.md` are identical by design. Codex reads this one; Claude Code
reads the other. Keep them in sync.

## What this is

A shared household recipe assistant. SQLite stores the recipes; an MCP server exposes
five tools over stdio; a Telegram household group and local MCP clients call the same
application services. `SPEC.md` (v3.5) is the source of truth for scope and staging.
WhatsApp exists only as a one-time, repeatable chat-export backfill.

**No hosted model API.** The server is deterministic. The agent that calls it (you, or a
headless `claude -p` run started by the Telegram host) parses free text, proposes
classifications and composes replies. `save_recipe` takes structured fields for that;
`correct_recipe(proposed_by_agent=true)` stores your classification proposal; a person's
correction without that flag overrides it.

## Architecture boundaries (enforced in review)

```
adapters/  (mcp, telegram, shortcut, nyt, whatsapp)  thin; no business logic
services/  (ingestion, categorization, recommendation, feedback, corrections,
            members, whatsapp_import, link_classification, fixtures, evals, container)
domain/    (models, taxonomy, ingredients, staples, dietary, ranking, feedback,
            references, urls, household)
providers/ (agent_brain: headless Claude Code runner; optional ModelClient impls for
            the Phase 2 comparison: OpenAI, deterministic fake, caching wrapper)
db/        (SQLite connection, migration runner, repositories: the only SQL)
settings.py  the only place environment variables are read
```

- No model calls outside `providers/`. Services receive a `model_factory` and call it lazily.
- No business logic in adapters. MCP tools map arguments to a service call and back.
- All configuration goes through `Settings`. Never read `os.environ` elsewhere.
- Deterministic code decides: dietary rules, filtering, scoring, dedup, URL canonicalization,
  ordinal references, Telegram allowlists. The model proposes classifications and extracts
  constraints; it never picks recipes.
- Member identity: writes take `member` (a key such as `alex`); the server falls back to
  `DEFAULT_MEMBER`. Members are declared in the private `.private/members.yaml`.
- Classifications below `CLASSIFICATION_CONFIDENCE_THRESHOLD` are saved with
  `needs_review` and shown with `?`. User corrections (`correct_recipe`) override the model
  and are appended to `.private/evals/corrections.jsonl`.
- NYT ingestion is a chain: `HttpRecipeFetcher` first, `PlaywrightRecipeFetcher` (the
  signed-in profile under `.private/`) only when the anonymous page carries no usable
  Recipe JSON-LD. Playwright is an optional extra; nothing but `make nyt-login` needs it.
- Migrations in `migrations/` are additive and immutable once released. Add a new file.
- Prompts live in `providers/prompts.py` and carry a version; bump it when wording changes.

## Ideas and follow-ups

`IDEAS.md` is the backlog. Add new ideas there with a tag (`follow-up`, `idea`, `ops`,
`deferred`) instead of building them unasked. Picking one up means updating `SPEC.md`
first, then building, then moving the entry to Done (no commit IDs: the public repo has different history).

## Commands

```
make setup        # uv sync, create .env from .env.example (never overwrites), init db
make doctor       # config, db, members, fixtures, MCP startup; secrets shown as set/unset
make demo         # load synthetic recipes and print three recommendations
make test         # offline unit + contract + integration tests (no credentials)
make lint         # ruff check + format check
make typecheck    # mypy --strict on src/
make eval         # synthetic evals always; private evals when .private/evals exists
make smoke        # opt-in live checks; each reports the missing variable names
make import-whatsapp / categorize / refresh-dietary / categorization-report
make classify-backlog  # brain classifies unclassified recipes (ARGS="--dry-run" or "--limit 5")
make refresh-taxonomy  # move stored "other" values onto newly added vocabulary (ARGS=--dry-run)
make serve        # MCP server over stdio (uv run --env-file .env recipe-mcp serve)
make serve-telegram / install-daemon   # long-polling host; launchd plists (bot + nightly backup)
make backup       # copy the database to .private/backups/, keeping the newest 14
make nyt-login    # one-time NYT sign-in; syncs the optional `browser` extra
uv run recipe-mcp smoke --brain        # one real headless Claude Code reply
```

## Testing layers

- `tests/unit`: pure domain logic (URLs, ingredients, staples, dietary, ranking, feedback,
  ordinal references, Telegram allowlists, settings).
- `tests/contract`: MCP tool schemas for all five tools via a real in-memory client, model
  output schemas, repository interfaces, Telegram message parsing, export parsing.
- `tests/integration`: NYT JSON-LD fixture, fake model, temporary SQLite, save ->
  categorize -> recommend, save -> correct -> re-query, idempotent export import, the
  Stage 1 gate, private-eval replay.

Every MCP tool has a contract test. Every bug fix adds a regression test. User
corrections become eval cases automatically.

## Secrets and private data

`.env` and `.private/` are git-ignored and must stay that way. Never put real keys,
Telegram ids, exports, member files or NYT session data in fixtures, docs, prompts or
commits. `SECURITY.md` has the threat notes.
