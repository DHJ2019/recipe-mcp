# Architecture

How recipe-mcp is built. What it should do is in
[docs/product-specs/recipe-mcp.md](docs/product-specs/recipe-mcp.md). The rules enforced in
review are in [AGENTS.md](AGENTS.md).

## Overview

```text
Alex / Sam personal Telegram accounts
                 |
                 v
        Telegram Bot API (long polling; outbound HTTPS only)
                 |
                 v
     Telegram host (Python, launchd daemon on an always-on Mac)
     - resolves ratings, replies, ordinal references and time corrections itself
     - otherwise starts one headless Claude Code run (the brain)
     - per-chat conversation state
                 |
             stdio MCP
                 |
                 v
         Recipe MCP server (deterministic, no model API key)
                 |
        shared application services
          /          |          \
         v           v           v
      SQLite     NYT fetcher    Optional ModelClient
      (WAL)      HTTP first     (Phase 2 comparison only)
                 Playwright
                 fallback

Codex / Claude Code --------> Recipe MCP server over stdio
```

The agent that calls the server does the semantic work: it parses free text, proposes
classifications and writes replies. The server stores, filters, ranks and checks.

## Decisions that shape the code

- One Python repository and one package, `src/recipe_mcp/`.
- SQLite in WAL mode. The repository layer isolates persistence, so Postgres could
  replace SQLite later.
- The Telegram host calls the Bot API directly over HTTPS (`getUpdates`, `sendMessage`).
  No webhook, no tunnel, no inbound port.
- The host and every MCP client each spawn their own MCP server process over stdio.
  WAL mode handles the low concurrency.
- NYT pages are read over HTTP with schema.org JSON-LD first. A signed-in Playwright
  profile is used only when the anonymous page has no usable recipe data.
- `MODEL_PROVIDER=none` is the default. The OpenAI, fake and caching clients exist for the
  multi-model comparison.

## Layers

```text
src/recipe_mcp/
├── adapters/      thin, no business logic
│   ├── mcp/        MCP server and tool schemas
│   ├── telegram/   long-polling host, Bot API client, reply composer
│   ├── nyt/        HTTP and Playwright fetchers, JSON-LD parser
│   ├── whatsapp/   chat-export parser for the backfill
│   └── shortcut/   empty stub for the deferred save endpoint
├── services/      ingestion, categorization, recommendation, feedback, corrections,
│                  members, whatsapp_import, link_classification, backups, fixtures,
│                  evals, container (wiring)
├── domain/        models, taxonomy, ingredients, staples, dietary, ranking, feedback,
│                  references, urls, household, limits
├── providers/     agent_brain (headless Claude Code runner), base ModelClient,
│                  factory, openai_client, fake, caching, prompts (versioned)
├── db/            connection, migration runner, repositories (the only SQL), backup
├── cli/           the recipe-mcp command (doctor, import, eval, backup and more)
└── settings.py    the only place environment variables are read
```

## Repository

```text
recipe-mcp/
├── src/recipe_mcp/          see Layers
├── migrations/              additive SQL files, immutable once released
├── tests/
│   ├── unit/                pure domain logic
│   ├── contract/            MCP tool schemas, model output schemas, repositories, parsers
│   ├── integration/         NYT fixture, fake model, temporary SQLite, end-to-end flows
│   └── fixtures/            NYT pages, a synthetic WhatsApp export sample
├── evals/
│   ├── recipes/             synthetic recipes and staples.yaml
│   ├── queries/             the initial recommendation requests
│   ├── images/
│   └── approved_results/
├── deploy/
│   ├── com.recipe-mcp.telegram.plist   bot daemon
│   ├── com.recipe-mcp.backup.plist     nightly backup
│   └── README.md                       running it on an always-on Mac
├── docs/
│   ├── product-specs/recipe-mcp.md     the spec and roadmap
│   └── decisions.md
├── .github/
│   ├── workflows/           ci.yml, audit.yml
│   └── dependabot.yml
├── AGENTS.md, CLAUDE.md, README.md, ARCHITECTURE.md, SECURITY.md, LICENSE
├── Makefile, pyproject.toml, uv.lock, .env.example
├── data/                    the SQLite database (ignored)
└── .private/                exports, browser profile, members, private evals (ignored)
```

## Testing layers

- `tests/unit`: URLs, ingredients, staples, dietary rules, ranking, feedback, ordinal
  references, Telegram allowlists, settings.
- `tests/contract`: all five MCP tools through a real in-memory client, model output
  schemas, repository interfaces, Telegram message parsing, export parsing.
- `tests/integration`: NYT JSON-LD fixture, fake model, temporary SQLite. Save then
  categorize then recommend, save then correct then re-query, idempotent export import,
  the Stage 1 gate, private-eval replay.
