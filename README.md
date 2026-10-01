# Recipe MCP

A small household recipe assistant that stores recipes in SQLite and exposes them
through the Model Context Protocol. Save an NYT Cooking link or an informal recipe,
get three grounded recommendations by ingredients, time, dietary needs and mood, rate
what you cooked, and correct anything the classifier got wrong. The same store is
reachable from a shared Telegram group, Codex and Claude Code.

The full design is in [SPEC.md](SPEC.md) (v3.5). There is no hosted model API anywhere in
the application: the MCP server is deterministic, and the semantic work is done by the
agent that calls it. At a terminal that agent is Claude Code or Codex. In the Telegram
group it is a headless `claude -p` run on your always-on Mac using your own subscription.

This README is the setup path, split into four levels. Level 1 works on a fresh clone
with no API keys, no NYT subscription, no Telegram bot and no private data.

## Why this exists

My partner and I send each other recipes we love, but in a chat they disappear. They
aren't searchable, we forget them, and we can't ask "what can we make tonight?"

This turns those shares into a private household cookbook. Save a link or a description,
then ask for ideas by time, ingredients on hand, diet or mood, and get suggestions only
from recipes you've saved. Your ratings and corrections shape what it suggests next.

A one-time WhatsApp import rescues the recipes already buried in a chat. Each household
runs its own copy, so you can use this to build your own.

## You'll need

- A Mac with macOS 14 or later, and [uv](https://docs.astral.sh/uv/).
- An MCP client: Claude Code or Codex.
- For the Telegram bot: an always-on Mac (Mac mini, iMac or a laptop that stays awake),
  a Claude subscription for headless Claude Code, and a Telegram bot token.

Level 1 below still needs no keys or accounts at all.

## What works today

- Save NYT Cooking links (from the NYT app's share sheet into Telegram, or from any MCP
  client) and informal recipes; links to other sites are kept as title-plus-URL entries.
- Three grounded recommendations by time, ingredients on hand, diet, cuisine, dish type,
  main ingredient and mood, drawn only from your own collection.
- Per-person ratings, "something we both like", corrections that permanently override
  classifications, and a one-time, repeatable import of an exported WhatsApp chat.
- A Telegram group bot that runs unattended on an always-on Mac, with Claude Code as its
  brain. A shared link is confirmed at once, then classified (cuisine, dish type, mood)
  and the confirmation updated in place a few seconds later.
- Not built yet: see [Future ideas](#future-ideas).

## Future ideas

Where it could go next. Each is written up, with trade-offs and open questions, in
[IDEAS.md](IDEAS.md):

- **Recipes beyond NYT Cooking:** read recipe data from other sites, and fill in links
  already saved from blogs, newspapers and videos.
- **Learning from the household:** remember stated preferences ("no cilantro for me") as
  hard rules, and learn from past corrections when classifying new recipes.
- **Smarter Telegram saves:** "what can we make from this fridge photo?"
- **More ways in and more places to run:** chat with your recipes from the Claude app,
  and host the bot on Linux or a small cloud server instead of a Mac.
- **Housekeeping:** a warning before the Claude token expires.

## What using it looks like

A short exchange in the household's Telegram group, with the demo household's recipes:

```text
Alex:  https://cooking.nytimes.com/recipes/...   (shared from the NYT Cooking app)
Bot:   Saved: Miso-Glazed Salmon with Roasted Cabbage
       Pescatarian · Japanese · 30 minutes
       (a few seconds later the same message reads)
       Pescatarian · Japanese · roast · light · 30 minutes

Sam:   something cozy under 45 minutes?
Bot:   1. Thai Pumpkin Soup, 40 min. Vegan, cozy and a little spicy.
          https://example.com/recipes/thai-pumpkin-soup
       2. Cabbage and White Bean Soup, 45 min. Light but warming.
          https://example.com/recipes/cabbage-white-bean-soup
       3. Cauliflower Dal, 40 min. Cozy, spicy, one pot.
          https://example.com/recipes/cauliflower-dal

Sam:   👍   (as a reply to the bot's message)
Bot:   Noted: Sam likes Thai Pumpkin Soup (both positive).
```

Links and ratings are answered in a second or two; classifying a link takes Claude Code
a few more seconds, and the bot then edits its confirmation. Questions go to Claude Code
and take around 15 seconds.

## Privacy: where your data lives

- **Your collection stays on your machine.** The database (`data/recipes.db`) and your
  private configuration (`.private/`, `.env`) are git-ignored and never leave the Mac.
  Each household runs its own copy: nothing is shared between households and there is no
  central server.
- **What does leave the machine:**
  - Telegram group messages pass through Telegram's servers, as with any Telegram chat.
  - Messages the bot hands to Claude Code are sent to Anthropic, together with the recipe
    details the tools return for that request (for example the three suggestions).
  - NYT pages are fetched from NYT; links to other sites are fetched once for their
    title.
- The recipe database itself is never uploaded as a whole.

See [SECURITY.md](SECURITY.md) for the full threat notes, including how the bot's Claude
Code is locked down to the recipe tools.

## Level 1: core local setup

**Supported:** macOS 14 or later on Apple Silicon or Intel; Python 3.13 (installed by
`uv` automatically); `uv` 0.5 or later; GNU Make (ships with Xcode command line tools).

```bash
brew install uv
```

```bash
git clone https://github.com/DHJ2019/recipe-mcp.git
cd recipe-mcp
make setup
```

`make setup` installs dependencies into `.venv`, copies `.env.example` to `.env` if
`.env` does not exist yet, and initialises `data/recipes.db`.

**`.env` versus `.env.example`:** the example file is committed and contains only
variable names and blank placeholders. Your `.env` is local, git-ignored, and the only
place credentials go. Never commit it and never paste its contents into a chat.

Check the installation, then load the synthetic sample recipes:

```bash
make doctor
```

```bash
make demo
```

`make demo` loads 15 invented recipes and two demo members (`alex` and `sam`), seeds a
few ratings, and prints three recommendations for "something cozy under 45 minutes".
Expected output is three titles from the synthetic set with time, tags and a reason,
for example Thai Pumpkin Soup, Cabbage and White Bean Soup and Cauliflower Dal.

Run the offline test suite:

```bash
make test
```

### Connect an MCP client

The server speaks MCP over stdio and reads its settings and any secrets from `.env`, so
nothing secret goes into a client configuration file. By default the server needs no API
key at all: it calls no model, and the client agent does the thinking. The launch command
is:

```bash
uv run --env-file .env recipe-mcp serve
```

**Claude Code.** A project-level `.mcp.json` is included, so opening Claude Code in
this directory offers the `recipe-mcp` server. To register it globally instead, replace
the path placeholder:

```bash
claude mcp add recipe-mcp -- uv --directory /ABSOLUTE/PATH/TO/recipe-mcp run --env-file .env recipe-mcp serve
```

**Codex.** Add to `~/.codex/config.toml`, replacing the path placeholder:

```toml
[mcp_servers.recipe-mcp]
command = "uv"
args = ["--directory", "/ABSOLUTE/PATH/TO/recipe-mcp", "run", "--env-file", ".env", "recipe-mcp", "serve"]
```

Then ask the client for "something cozy under 45 minutes" and you should get the same
three synthetic recipes. The five tools are `save_recipe`, `recommend_recipes`,
`get_recipe`, `rate_recipe` and `correct_recipe`. Try "save this: tuna salad with
tomato, quinoa, cucumber, arugula and seeds, need to season the tuna" too: the agent
parses it and calls `save_recipe` with structured fields, and the server applies the
dietary rules. Set `DEFAULT_MEMBER` in `.env` to your member key once you reach Level 2
so ratings from your machine are attributed to you without passing `member` on every call.

Level 1 is complete when `make test` passes and an MCP client returns three
recommendations.

## Level 2: personal household setup

Nothing in this level is committed. All private files live under `.private/`, which is
git-ignored.

1. Declare the household in `.private/members.yaml`. Telegram ids can be added later:

   ```yaml
   members:
     - key: alex
       display_name: Alex
       telegram_user_id: 123456789
       whatsapp_export_name: Alex
     - key: sam
       display_name: Sam
       telegram_user_id: 987654321
       whatsapp_export_name: Sam
   ```

   The file is synced into the database on every start. Set `DEFAULT_MEMBER=alex` in
   `.env` on your own machine. From here on `data/recipes.db` holds your real
   collection: see [Back up your recipes](#back-up-your-recipes).

2. Export your existing WhatsApp recipe chat (WhatsApp > chat > Export Chat > Without
   Media) and save it as `.private/whatsapp-export.txt`, or point
   `WHATSAPP_EXPORT_PATH` in `.env` at it.

3. Preview the links that will be imported, then import them. NYT links need network
   access. The import is idempotent, so re-run it after a fresh export whenever you
   like. Links to other sites are kept as title-plus-URL stubs and listed separately in
   the report. Imported recipes get rule-derived facets (dietary, effort) only; to
   classify cuisine, dish type and mood in bulk, run `make classify-backlog` once the
   brain is set up (Level 3; one headless Claude Code run per recipe, see step 7), ask
   Claude Code in this repo to "go through the recipes that need classification and
   propose facets" and it will use `correct_recipe` with `proposed_by_agent`, or run it
   with a server-side model (Level 3) and `make categorize`.

   ```bash
   uv run recipe-mcp import-whatsapp --dry-run
   ```

   ```bash
   make import-whatsapp
   ```

4. Review the batch categorization report. Anything below the confidence threshold is
   marked for review. Corrections override the model permanently and become private
   regression cases:

   ```bash
   make categorization-report
   ```

   ```bash
   uv run recipe-mcp correct 12 cuisine thai
   ```

5. Staples (assumed on hand, excluded from "missing" counts) live in
   `evals/recipes/staples.yaml`. Edit it and run `make categorize` to re-apply.

6. After the ingredient parser or its lexicons change, re-parse stored ingredient lines
   and re-run the dietary rules. Only ingredients and `dietary_suitability` are rewritten:

   ```
   make refresh-dietary ARGS=--dry-run   # list the recipes that would change
   make refresh-dietary
   ```

7. Classify recipes that still have no cuisine, dish type or mood with the brain. Each
   recipe is one headless Claude Code run on your subscription, so start with a dry run
   and a small limit. It pauses between runs, stops after three failures in a row, and
   is safe to stop and re-run (finished recipes drop out):

   ```
   make classify-backlog ARGS=--dry-run       # how many, and which
   make classify-backlog ARGS="--limit 5"
   make classify-backlog
   ```

## Level 3: optional live integrations

Each integration is optional and independent. `make doctor` shows which are configured;
`make smoke` runs live checks only for the ones that are, and names any missing
variables without printing values.

**The brain (Claude Code).** `.env` defaults to `BRAIN=claude-code` and
`CLAUDE_CODE_BIN=claude`. Install Claude Code on the always-on Mac and log in once
(`claude` then `/login`). For unattended running, create a long-lived token and put it in
`.env` on a single line (a wrapped paste truncates it; `make doctor` flags that):

```bash
claude setup-token
```

```dotenv
CLAUDE_CODE_OAUTH_TOKEN=<token>
```

The token lasts a year. The bot removes `ANTHROPIC_API_KEY` from the brain's environment,
so replies use your subscription rather than per-token API billing even if your shell
exports a key. `make doctor` shows which credential the brain uses. To watch one headless
reply against the demo data:

```bash
uv run recipe-mcp smoke --brain
```

Set `BRAIN_MODEL` to pin a model and `BRAIN_TIMEOUT_SECONDS` / `BRAIN_MAX_TURNS` to
bound each reply. Whether unattended use fits your subscription's terms is between you
and Anthropic; a local model via Ollama is the fallback brain if that changes.

**Optional server-side model.** `MODEL_PROVIDER=none` is the default and nothing needs
it. For the Phase 2 comparison you can set `MODEL_PROVIDER=openai` plus
`OPENAI_API_KEY`, or `MODEL_PROVIDER=fake` for a deterministic stand-in; then
`make categorize` and free-text `save_recipe` work without an agent.

```bash
make smoke
```

**NYT Cooking.** Public recipe pages are fetched over HTTP and parsed from their
schema.org JSON-LD. Test one with:

```bash
uv run recipe-mcp smoke --nyt-url https://cooking.nytimes.com/recipes/<id>-<slug>
```

Subscriber-only recipes need a signed-in browser. Playwright is an optional extra, so
install it and sign in once:

```bash
make nyt-login
```

That syncs the `browser` extra, downloads Chromium and opens a headed window against a
dedicated profile under `.private/`. You type your NYT credentials into that window; the
code never reads, types or stores a password, and only the cookie *names* and expiry are
ever surfaced. `make doctor` then reports how many days the session has left.

Once the profile exists, saves fall back to it automatically: HTTP first, and the browser
only when the anonymous page carries no usable recipe data. Nothing else changes -- the
MCP server, the Telegram host and the test suite never need a browser.

**Telegram.** Step by step:

1. In Telegram, message `@BotFather`: `/newbot`, pick a name and a username. Copy the
   token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Still in BotFather: `/setprivacy`, choose your bot, choose **Disable**, so it sees
   every message in the group.
3. Create a private group and add the other household members and the bot.
4. Find the numeric ids. Each member messages `@userinfobot` to get their user id; put
   each member's user id in `TELEGRAM_ALLOWED_USER_IDS` (comma-separated) and in
   `.private/members.yaml`. For the group id,
   post any message in the group, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the negative
   `chat.id`; put it in `TELEGRAM_GROUP_CHAT_ID`.
5. `make doctor` should show telegram and brain as configured. Then:

   ```bash
   make smoke
   ```

   posts a test line to the group, and

   ```bash
   make serve-telegram
   ```

   starts the long-polling host in the foreground. Send an NYT link, ask for something
   cozy, reply 👍 to a result, or say "the second one takes about 30 minutes".

The bot long-polls, so no webhook or tunnel is needed. Ratings by reply, ordinal
references and time corrections are handled without the brain; everything else is a
headless Claude Code turn with the last ten turns and last result list as context.

**Always-on deployment.** Run the bot on an always-on Mac (Mac mini, iMac or a laptop
that stays awake). See [deploy/README.md](deploy/README.md) and `make install-daemon`
(run it as your normal user; the daemon starts at boot and runs as you). The daemon uses
launchd, so it is macOS only; Linux or cloud hosting is an idea in [IDEAS.md](IDEAS.md).

**Restarting with FileVault on.** If the Mac uses FileVault, a normal restart stops at the
disk unlock screen and nothing, including the bot, runs until someone types the password.
Once the Mac has booted the bot needs no login. For planned restarts, use a one-time
unlock so the Mac comes back fully and the bot starts unattended:

```bash
sudo fdesetup authrestart
```

After a power cut the Mac still waits at the unlock screen. Turning FileVault off, or
hosting elsewhere, are the alternatives; see [IDEAS.md](IDEAS.md).

## Level 4: contributor setup

Read [AGENTS.md](AGENTS.md) (identical to `CLAUDE.md`) for the architecture
boundaries. In short: adapters are thin, services hold the workflow, domain code is
deterministic, and `providers/` is the only place a model is called.

```bash
make lint
```

```bash
make typecheck
```

```bash
make eval
```

- **Tests** are layered as `tests/unit`, `tests/contract` and `tests/integration`.
  Every MCP tool has a contract test. Bug fixes add a regression test.
- **Evals** live under `evals/` (synthetic recipes, the tuna-quinoa-salad fixture, the
  ten initial queries, staples). `make eval` runs them offline against the fake model
  and also replays `.private/evals/` when that directory exists.
- **Migrations** are numbered SQL files in `migrations/`, applied in order on startup,
  and never edited after release.
- **Prompts** are versioned in `src/recipe_mcp/providers/prompts.py`; model outputs
  are cached by input hash, prompt version and model name.
- **Secret scanning** runs in CI with gitleaks. Run `git check-ignore .env .private/x`
  before adding anything private.
- **Pull requests** should keep `make test lint typecheck eval` green and note which
  spec stage they advance.

## Back up your recipes

`data/recipes.db` is the whole collection: recipes, ratings, corrections and members.
`make install-daemon` sets up a nightly backup to `.private/backups/` that keeps the last
14 days, and `make backup` makes one by hand. Both are safe while the bot is running, and
`make doctor` warns if the newest backup is more than a day and a half old. Restoring is
covered in [deploy/README.md](deploy/README.md#backups).

Those copies live on the same disk, so also let Time Machine (or another off-machine
backup) include the repository folder. Keep every copy private: it holds your whole
household collection.

## Troubleshooting

- **"no model is configured to parse free text; pass title and ingredients".** Expected
  with `MODEL_PROVIDER=none`: the calling agent should parse the description and pass
  structured fields. Set `MODEL_PROVIDER=fake` or `openai` only if you want the server
  itself to parse.
- **"CLAUDE_CODE_BIN ('claude' not found on PATH)".** Install Claude Code on the
  always-on Mac and make sure the launchd `PATH` in `deploy/` includes it, or set
  `CLAUDE_CODE_BIN` to the full path.
- **The bot replies "Sorry, I couldn't work that out".** Run
  `uv run recipe-mcp smoke --brain` to see the underlying `claude -p` error; usually a
  login or `--max-turns` problem.
- **"unknown member".** Declare the member in `.private/members.yaml` or set
  `DEFAULT_MEMBER` to an existing key; `make doctor` lists the configured keys.
- **`make doctor` says no `.env` file.** Run `make setup`; it creates one from the
  example without touching an existing file.
- **MCP client cannot connect.** Run the launch command by hand from the repo
  directory; it should sit waiting on stdin. Check the absolute path in your client
  config and that `uv` is on the client's PATH (`which uv`).
- **Database errors.** Back up first (see [Back up your recipes](#back-up-your-recipes)),
  then run `make doctor` to see what is wrong. If you only ever loaded the demo data, you
  can delete `data/recipes.db*`, run `make setup` again and reload it with `make demo`.
  Never delete the database once it holds your real collection; restore from a backup
  instead.
- **NYT page has no recipe data / returns 401.** The recipe is subscriber-only: run
  `make nyt-login` so the authenticated fallback can take over, or check the URL is a
  recipe page. Short `nyti.ms` links are resolved automatically.
- **"playwright is not installed".** Run `make nyt-login`, which syncs the `browser`
  extra and downloads Chromium. A plain `make setup` deliberately leaves it out.
- **"the stored NYT session is not signed in or has expired".** Run `make nyt-login`
  again; `make doctor` shows the expiry date.
- **Telegram polling errors.** Check the token with BotFather, confirm the bot is in
  the group with privacy mode disabled, and that the ids in `.env` are numeric.
- **`make smoke` says chat not found although the browser test works.** Check whether
  another `TELEGRAM_BOT_TOKEN` is exported in your shell (`echo $TELEGRAM_BOT_TOKEN`) and
  unset it, so the token in `.env` is the one used.

## Licence

MIT. See [LICENSE](LICENSE). NYT Cooking content stays on NYT Cooking; this tool
stores metadata and deep links only.
