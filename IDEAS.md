# Ideas and follow-ups

A running list of features and fixes that are not built yet. `SPEC.md` stays the source
of truth for what the system does; when an idea is picked up it is written into the spec
first, built, and then removed from this list (or moved to **Done**).

## Tags

- `follow-up`: agreed and wanted; next in line.
- `idea`: worth exploring; needs a decision before any work.
- `ops`: running and maintaining the Mac mini, not product features.
- `deferred`: consciously parked (mirrors SPEC.md section 23).

Each entry says why it matters, what it would take, and any open question.

---

## Follow-ups

### Fill in recipes linked from other sites `follow-up`

**Why:** only NYT Cooking links are read. Links to other sites (food blogs, newspaper
recipe pages, videos) are saved as `other` stubs with just a title and URL, with no
ingredients or classifications, so cuisine, dish type and ingredient filters never match
them. In a collection imported from a shared chat these can be a large share of all saves.

**What a sample showed:** in a sample of saved non-NYT links from a real collection, only
about one in ten pages carried standard recipe data. Roughly half loaded but had none
(articles, restaurant pages, recipes without structured markup), about a third refused
automated requests or were dead, and videos and social posts never carry it. So the
simple approach helps future saves from proper recipe sites far more than old links.

**What it takes, in three levels:**
1. **Simple (planned first, right after the first release):** parse Recipe JSON-LD from
   any site, not just NYT. The existing `jsonld` parser already handles the standard
   format; add a generic fetcher for other domains that reuses the title fetcher's
   protections (public addresses only, checked on every redirect, size cap), and fall
   back to today's title-plus-URL stub when a page has no recipe data. Add a backfill
   command that retries existing stubs. A few hours with tests.
2. **Smart:** have Claude extract the recipe from pages without structured data. This
   reopens a door the security review closed: the bot's Claude Code has no web access so
   planted text on a page can't steer it. A safe design has the server fetch and strip the
   page to plain text, pass only that to the agent as clearly marked untrusted data, and
   store the result as a `needs_review` draft. Needs its own spec and security pass.
3. **Sites that refuse automated requests:** only a signed-in browser per site, as with
   NYT. Not worth it until a specific site matters.

Videos and social posts stay stubs; the brain can classify them from the title alone,
marked `needs_review`.

**Open questions:** this lifts the "Recipe sites beyond NYT Cooking" deferral, so SPEC.md
section 23 changes first. Is level 2 worth the extra attack surface once level 1 is in
daily use?

### Classify links shared in Telegram `follow-up`

**Why:** NYT links saved from the group skip the brain so the reply is instant, and with no
server-side model nothing fills in cuisine, dish type or mood. A link gets only dietary and
time tags ("Spicy Garlic Shrimp Stir-Fry · Pescatarian · 20 minutes").
**What it takes:** after the instant "Saved" reply, run one headless Claude Code turn that
calls `get_recipe` and `correct_recipe(proposed_by_agent=true)`, then post a short follow-up
reply ("Chinese · stir-fry · spicy"). Tests with the fake brain.
**Open question:** follow-up message, or edit the original confirmation in place?

### Warn before the Claude Code token expires `follow-up` `ops`

**Why:** `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` lasts one year. When it lapses
the bot only says "Sorry, I couldn't work that out."
**What it takes:** record the creation date in `.env`, have `make doctor` warn 30 days
ahead, and make the brain's 401 produce a clear log line.

### Nightly database backup `follow-up` `ops`

**Why:** the whole collection lives in one SQLite file on the Mac mini.
**What it takes:** a launchd job running SQLite's online backup into `.private/backups/`,
keeping 14 days (SPEC 19A), plus a `make doctor` check that the newest backup is recent.

### Free-form household tags `follow-up`

**Why:** the controlled taxonomy can't hold personal labels ("Sam's birthday",
"freezer-friendly", "guests").
**What it takes:** spec first, then a tags table, `save_recipe` and `correct_recipe`
support, and a `tag` filter on `recommend_recipes`.

---

## Ideas

### Learn from the household over time `idea`

**Why:** today the assistant adapts only through deterministic signals: ratings change
ranking (dislikes are hard-filtered, "we both like" uses the lower score, untried recipes
lean towards ones similar to liked ones), recent cooking is pushed down, and corrections
are permanent. The brain starts fresh on every message, so it does not learn from past
corrections, stated preferences, or what you actually pick.
**What it takes, in order of value:**
- Remember stated preferences as hard rules per member ("I don't eat cilantro", "no pork
  on weeknights"), stored in the database and applied by the ranking filters.
- Feed recent corrections (`.private/evals/corrections.jsonl`) to the brain as examples
  when it classifies new recipes.
- Grow the taxonomy from repeated `other` proposals, with a review step.
- Record which recommendation was chosen and use it to tune ranking weights.
**Open question:** which of these would you actually notice day to day?

### Chat with the recipes from the Claude app `idea`

**Why:** longer conversations and planning in the Claude app, while Telegram stays the quick
shared channel. Saving, rating and correcting would work there too, on the same database.
It is also plainly interactive use of the subscription, unlike unattended `claude -p`.
**What it takes:** serve the MCP server over HTTPS (the SDK supports streamable HTTP), put
it behind authentication and a public address (for example a Cloudflare Tunnel, since
Claude's servers connect to custom connectors from the cloud, not from your phone), then add
it once as a custom connector in Claude settings.
**Open questions:** whose identity Claude-app writes use (Alex by default); whether Sam
gets their own connector; which host (see next two ideas).

### Linux or cloud hosting via systemd `idea`

**Why:** the daemon uses launchd, so today the bot only runs on a Mac. A Linux box or a
small cloud server (about $5–7 a month) would open it to people without an always-on Mac.
It also sidesteps FileVault: the Mac can't start the bot after a restart or power cut until
someone types the password, while a server restarts unattended and doesn't depend on home
power or internet.
**What it takes:** a systemd service file alongside the launchd plist, setup docs, moving
`data/recipes.db`, `.env` and `.private/`. Local Claude Code and Codex keep working by
running the MCP server on the server over SSH. The NYT signed-in browser profile is the
awkward part to recreate there.
**Open question:** is recovery after a power cut worth a monthly bill and data held on a
rented machine?

### Keep the recipes in Google Drive or a Shared Drive `idea`

**Why:** make the collection visible and backed up outside the Mac, possibly shared with
Sam directly.
**What it takes, and the catch:** Drive can store files but can't run anything. The MCP
server is a program that has to run somewhere, so Drive alone can't replace the Mac or a
cloud server. Putting the live SQLite file in a synced folder is also unsafe: two copies
writing through sync can corrupt it. Realistic versions:
- nightly backup of `data/recipes.db` into Drive (read-only copy, safe);
- a mirrored Google Sheet of recipes, readable in Drive and by Claude's Google Drive
  connector, rebuilt after each change (no dietary rules or ranking, but browsable
  anywhere);
- a different storage backend (hosted Postgres) if the server moves to the cloud; the
  repository layer is already isolated for this.
**Open question:** is the goal backup, sharing, or running without the Mac?

### Review recipes from Claude Code on the web `idea`

**Why:** the code already lives in a private GitHub repo. If the recipes were there too,
Claude Code on the web (claude.ai/code) could open the repo in a cloud session and review or
tidy the whole collection from any device, with no Mac involved.
**What it takes:** Claude Code on the web can only see what is in the repo, and the live
database is deliberately not in Git. So: a nightly export of every recipe as a small text
file (YAML) into the private repo or a separate private data repo, and an import step that
applies reviewed changes back to the database. Alternatively, once the bot runs on a cloud
server, expose the MCP server to cloud sessions instead of copying data.
**Open questions:** is household recipe data acceptable in a private GitHub repo; how to
avoid conflicts between the bot's writes and a cloud session's edits.

### Offline export for the phone `idea`

**Why:** see and search the collection when the Mac is down.
**What it takes:** `recipe-mcp export` writing one searchable HTML or Markdown file to iCloud
Drive (or Google Drive), refreshed nightly. Read-only, no recommendations.

### Local model fallback brain (Ollama) `idea`

**Why:** if unattended use of the Claude subscription stops being an option, the bot needs a
brain that runs on the Mac mini itself.
**What it takes:** a second `Brain` implementation behind `BRAIN=ollama`; tool calling
against the same MCP server.

### Photo input `idea`

**Why:** "what can we make from this fridge photo" (SPEC stage 4).
**What it takes:** Telegram `getFile`, temporary storage under `.private/`, ingredient
extraction by the brain, confirmation of uncertain items, then `recommend_recipes`.

---

## Ops

### Restarting the Mac mini with FileVault on `ops`

After a normal restart the Mac waits at the FileVault unlock screen, and nothing (network,
launchd, the bot) runs until someone types the password. For planned restarts use:

```bash
sudo fdesetup authrestart
```

It unlocks the disk for that one restart so the bot comes back unattended. After a power
cut the Mac powers on (`autorestart` is enabled) but still waits for the password. See the
cloud-hosting idea above if that matters.

### Log file naming `ops`

The bot writes its log lines to `/Library/Logs/recipe-mcp/telegram.err.log`;
`telegram.log` stays empty. Either log to stdout or rename the paths so the obvious file is
the useful one.

---

## Deferred

Mirrors SPEC.md section 23; kept there as the decision record.

- WhatsApp Business sender as a second live channel `deferred`
- Recipe sites beyond NYT Cooking `deferred` (see "Fill in recipes linked from other sites")
- iOS Shortcut save endpoint `deferred`: a share-sheet Shortcut posting a URL to a local
  `POST /save` on the Mac, reachable only over Tailscale (SPEC.md "Optional save-only
  shortcut"). `adapters/shortcut/` is an empty stub and the `SHORTCUT_*` settings in
  `.env.example` do nothing yet.
- Persistent pantry state, shopping lists, voice notes `deferred`
- Private web reading interface `deferred`

---

## Done

- Retry Telegram `getMe` at startup instead of crashing.
- Brain runs on the subscription; Anthropic API keys stripped from its environment.
- Daemon runs as the invoking user, not root.
