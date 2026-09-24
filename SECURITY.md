# Security notes

This is a personal, local-first tool that runs unattended on a Mac mini. The risks
below are the ones that matter for that deployment.

## Secrets and configuration

- All secrets live in the local `.env`, created from `.env.example` by `make setup`.
  `.env`, `.env.*` (except the example) and `.private/` are git-ignored; `make setup`
  never overwrites an existing `.env`.
- `recipe-mcp doctor` prints whether each secret is set, never its value.
  Missing-configuration errors list variable names only.
- Household members, including Telegram user ids, are declared in
  `.private/members.yaml`, which is never committed.
- CI runs with `MODEL_PROVIDER=fake` and an in-memory database and never reads a
  developer `.env`. A gitleaks secret scan runs on every push.

## The brain (headless Claude Code)

Messages from the group, and recipe text taken from web pages, reach an AI agent. Treat
both as untrusted input: the protections below are enforced by configuration, not by
asking the model to behave.

- **No built-in tools.** `claude -p` runs with `--tools ""`, so the agent has no file,
  shell, web, agent or scheduling tools at all. `--strict-mcp-config` plus an explicit
  `--allowedTools` list leaves exactly the five recipe tools. A regression test checks
  the command line. (An earlier version relied on `--allowedTools` alone; a live probe
  showed the built-in tools were still available, and the model's own refusal was the
  only thing stopping it reading files.)
- **Isolated working folder.** The agent runs from `.private/brain/` (mode 700), which is
  empty apart from its own MCP config with absolute paths. The repository, `.env` and
  project instructions are out of its reach and out of its context.
- **No message transcripts.** `--no-session-persistence` stops Claude Code saving each
  household conversation under `~/.claude/projects/`; stdin is `/dev/null` so nothing
  extra is appended to the prompt.
- **Subscription, not API billing.** `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are
  removed from the agent's environment; it authenticates with `CLAUDE_CODE_OAUTH_TOKEN`
  (from `claude setup-token`) or the keychain login.
- **Bounded work.** Each reply is limited by `BRAIN_MAX_TURNS` and `BRAIN_TIMEOUT_SECONDS`.
  The subprocess gets an argument list, never a shell string.
- **What remains possible:** a crafted message or recipe text could make the agent call
  the recipe tools wrongly (save, rate or correct something) or reply with misleading
  text. There is no delete tool, only allowlisted members can message the bot, and
  corrections are recorded, so this is recoverable.
- Unattended use of a consumer subscription is the household's arrangement with
  Anthropic; nothing here embeds or proxies credentials.

## Telegram

- The bot uses long polling: outbound HTTPS only, no inbound port, no webhook, no tunnel.
- Only numeric user ids in `TELEGRAM_ALLOWED_USER_IDS`, and only in the group
  `TELEGRAM_GROUP_CHAT_ID` or a private chat with an allowlisted member, are served.
  Everything else is dropped and logged as rejected without content.
- The bot never sends a message that is not a reply to a message in the group.
- Message contents and media are not logged by default. Photos are written to
  `TEMP_MEDIA_DIR` under `.private/` and deleted after processing.
- The bot token is a secret; keep it in `.env` only.

## NYT Cooking

- Normal fetches are plain HTTP for schema.org JSON-LD and store metadata plus a
  deep link, not the recipe text. Access relies on the household's own subscription.
- The optional authenticated fallback (Stage 2) uses a dedicated Playwright browser
  profile in `.private/`. The application never sees or stores an NYT password; you
  log in interactively once and the browser session is kept locally.
- Final URLs after redirects are validated against `cooking.nytimes.com` before parsing.
  Authenticated browsing is restricted to approved recipe domains.
- Links to other sites are stored as title-plus-URL stubs after a single anonymous GET. The
  fetch refuses private, loopback and link-local addresses (checked on every redirect hop,
  so a link can't reach the router or other devices on the home network) and reads at
  most 200 KB.

## Local MCP server

- The server runs over stdio only and is launched by the local MCP client (Claude
  Code, Codex, or the Telegram host). It opens no network port.
- `save_recipe`, `rate_recipe` and `correct_recipe` write to the local SQLite file;
  there is no delete tool. Tool results never include configuration values.
- The MCP client configuration launches `uv run --env-file .env recipe-mcp serve` from
  the repository, so the model key stays in `.env` and out of client config files.

## Optional shortcut endpoint

- `POST /save` (deferred) must bind only to the Tailscale interface, never `0.0.0.0`.

## Database and private evals

- `make setup` sets `data/` and `.private/` to mode 700 so other accounts on the Mac can't
  read recipes, member ids or exports.

- SQLite in WAL mode under `data/`, git-ignored. All queries are parameterised.
- Migrations are forward-only and applied automatically at startup.
- `.private/evals/` holds real recipes, queries and every correction; it is never
  committed and `make eval` reports it separately from the synthetic set.

## Dependencies and history

- Dependencies are locked in `uv.lock`; `uvx pip-audit` against the export found no known
  vulnerabilities (2026-09-24).
- The public repository starts from a single commit with no personal identifiers; the
  private development history is not published. CI runs gitleaks on every push.

## Reporting

This is a personal project; open an issue in the repository if you find a problem.
