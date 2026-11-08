# recipe-mcp: agent map

## What this is

A shared household recipe assistant. SQLite stores the recipes; an MCP server exposes
five tools over stdio; a Telegram household group and local MCP clients call the same
application services. WhatsApp exists only as a one-time, repeatable chat-export backfill.

**No hosted model API.** The server is deterministic. The agent that calls it (you, or a
headless `claude -p` run started by the Telegram host) parses free text, proposes
classifications and composes replies. `save_recipe` takes structured fields for that;
`correct_recipe(proposed_by_agent=true)` stores your classification proposal; a person's
correction without that flag overrides it.

## Where things are

| Path | What |
|---|---|
| `src/recipe_mcp/` | The package: adapters, services, domain, providers, db, cli, settings |
| `tests/` | `unit/`, `contract/`, `integration/`, `fixtures/` |
| `evals/` | Synthetic recipes, staples and queries for `make eval` |
| `migrations/` | SQL migrations |
| `deploy/` | launchd plists and `deploy/README.md`, how to run the always-on Mac |
| `ARCHITECTURE.md` | Layers, the repository tree, testing layers |
| `docs/product-specs/recipe-mcp.md` | The spec (v3.5): scope, tools, data model, Roadmap (section 19) |
| `docs/decisions.md` | One line per decision |
| `SECURITY.md` | Threat notes |

## Commands

```
make check        # lint, typecheck, test, eval: run before you push
make setup        # uv sync, create .env from .env.example (never overwrites), init db
make doctor       # config, db, members, fixtures, MCP startup; secrets shown as set/unset
make test         # offline unit + contract + integration tests (no credentials)
make eval         # synthetic evals always; private evals when .private/evals exists
make smoke        # opt-in live checks; each reports the missing variable names
make serve        # MCP server over stdio (uv run --env-file .env recipe-mcp serve)
make serve-telegram / install-daemon   # long-polling host; launchd plists (bot + nightly backup)
make help         # every target: lint, typecheck, demo, backup, imports, refreshes, nyt-login
uv run recipe-mcp smoke --brain        # one real headless Claude Code reply
```

## Boundaries (enforced in review)

- Adapters (`mcp`, `telegram`, `shortcut`, `nyt`, `whatsapp`) are thin. MCP tools map
  arguments to a service call and back. Services hold the workflow; domain code is pure.
- No model calls outside `providers/`. Services receive a `model_factory` and call it lazily.
- `db/` holds the only SQL. All configuration goes through `Settings` in `settings.py`.
  Never read `os.environ` elsewhere.
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
- New ideas go in the spec's Roadmap (section 19) with a tag (`follow-up`, `idea`, `ops`,
  `deferred`) instead of being built unasked. Picking one up means writing it into the spec
  first, then building, then removing it from the Roadmap.
- `.env` and `.private/` are git-ignored and must stay that way. Never put real keys,
  Telegram ids, exports, member files or NYT session data in fixtures, docs, prompts or
  commits. Never cite commit ids or private issue numbers in docs: the public copy has
  different history.

## Done means

The golden principles below say what done means in every repo. On top of them:

- Every MCP tool has a contract test.
- Every bug fix adds a regression test. User corrections become eval cases automatically.
- Migrations in `migrations/` are additive and immutable once released. Add a new file.
- Prompts live in `providers/prompts.py` and carry a version. Bump it when wording changes.

## Rules

<!-- golden-principles:start -->
## Golden principles

These rules come from dhj-factory/golden-principles.md. Change them there, not here.

### Layout
- Keep AGENTS.md, CLAUDE.md, README.md and ARCHITECTURE.md at the root. Nothing else.
- Make CLAUDE.md `@AGENTS.md` plus Claude-only lines. Keep AGENTS.md a map that points elsewhere.
- Put detail for one area in `.claude/rules/` with a `paths:` list, so it loads only when needed.
- Put every other doc under `docs/`: `product-specs/`, `exec-plans/active/`, `exec-plans/completed/`, `runbooks/`, `decisions.md`, `generated/` or `references/`. Datasets and reports go in `evals/`.
- Declare markdown that is data, not docs, in `.factory.yaml` under `docs_allow`.

### Never a file
- Handovers, handoffs, task cards, status notes and task lists go in GitHub issues and the Factory Project.
- Audits, reports and findings put their conclusion in a spec or `docs/decisions.md`. Raw output goes in `docs/generated/` or stays uncommitted.
- Prompts that get run become skills in `.claude/skills/`, or live in the code folder that loads them.
- Counts and numbers that change are generated by a script, never typed.
- Never keep a second copy. Link to the first one.
- Delete archives. Git history keeps them.

### Limits
- CLAUDE.md and AGENTS.md each aim for 100 lines. Over 150 warns. Over 200 fails.
- What loads at session start aims for 3,000 tokens. Over 5,000 warns. Over 8,000 fails.

### Work
- One issue, one branch, one PR, one agent. Never two agents on the same area or migration sequence.
- Branch from main and land on main. There is no staging branch.
- Write production only from a clean main checkout, and record the commit.
- Only TalentF changes the TalentFoundry schema. Other repos declare what they read.
- Run `make check` before you push. Never skip, disable or weaken a test or eval to get green.
- Stop after three fix cycles and comment on the issue with your evidence.

### Tickets and done
- Tickets scale with the risk tier. Tier A (docs, lint, tests, dependency bumps) is a one-line issue, done when CI is green. Tier B is a slice with 1 to 3 acceptance criteria. Tier C is a slice under an epic, with full criteria and a real check.
- A slice is one PR, one repo and one risk tier, and leaves main working. An epic exists only when a feature has 3 or more slices.
- Every acceptance criterion names its proof: a test, an eval and its bar, a command and its output, or a named manual check.
- Done means: each criterion met with its proof linked on the issue, tests added (a regression test for every bug fix), `make check` and CI green, evals at or above their bar, docs updated in place, and the handoff comment written.
- A different model from the builder reviews Tier B and C work. Tier C also needs Dan.
- Each repo adds its own rules under "Done means" in its AGENTS.md.

### Secrets
- Never put secrets in repos, issues or prompts. Use the password manager, environment secrets or an ignored `.env`.
<!-- golden-principles:end -->

## Where to look next

- How it is built: `ARCHITECTURE.md`
- What it should do, and what comes next: `docs/product-specs/recipe-mcp.md`
- Running the always-on Mac: `deploy/README.md`
- Why things are the way they are: `docs/decisions.md`
- Open work: this repo's GitHub issues and the Factory Project
