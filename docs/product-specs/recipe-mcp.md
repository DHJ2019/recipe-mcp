# Recipe MCP — Project Specification

**Author:** recipe-mcp contributors  
**Status:** Draft v3.5  
**Primary objective:** Learn MCP by building a useful shared household recipe assistant  
**Initial clients:** Telegram (shared household group), Codex, and Claude Code  
**Repository:** Developed in a private repository. A public copy, `DHJ2019/recipe-mcp`, is published from it by hand  
**Runtime:** Python 3.13 on an always-on Mac mini  
**Names:** Alex and Sam are placeholders for the two household members throughout this document.

---

Changes between spec versions are in [docs/decisions.md](../decisions.md), one line per decision.

---

## 1. Why This Exists

Alex and Sam already share recipes through WhatsApp, but the conversation is not a structured, searchable collection. Finding a suitable dinner still requires remembering what was saved, opening links individually, and mentally comparing recipes with the ingredients, time, and mood of the evening.

This project creates a small personal recipe intelligence service that:

- imports the recipes already shared in WhatsApp;
- saves new NYT Cooking links and informal personal recipes;
- categorizes recipes consistently;
- recommends recipes using ingredients, time, dietary suitability, and mood;
- accepts fridge or pantry photographs;
- learns explicit preferences from both household members; and
- exposes the same recipe store through MCP to a shared Telegram group, Codex, and Claude Code.

The project is also a deliberate MCP experiment. Phase 1 establishes a single-model quality baseline. Phase 2 substitutes individual tasks with smaller or local models and evaluates the quality, latency, and cost difference.

---

## 2. Product Principles

1. **The database stores the recipes; MCP exposes the capabilities.** MCP is not the datastore.
2. **Use one capable model first.** Do not build model routing before the complete experience works.
3. **Use deterministic code wherever possible.** Parsing, dietary validation, filtering, scoring, deduplication, and authorization should not depend on a model.
4. **Categorize from real recipes and real queries.** Begin with a small controlled taxonomy and extend it only when actual use requires it.
5. **Store NYT metadata and deep links, not a replacement copy of NYT Cooking.**
6. **Keep interfaces thin.** Telegram and MCP call the same application services. A later WhatsApp adapter must be able to do the same without touching the services.
7. **Prefer a working vertical slice over comprehensive infrastructure.**
8. **Turn user corrections into evaluation cases.**

---

## 3. MVP Outcomes

The MVP succeeds when Alex or Sam can:

1. From the NYT Cooking app, tap Share, choose Telegram, and send the recipe link to the household recipe group. The bot imports, categorizes, and confirms the saved recipe in the group.
2. Describe a personal recipe in ordinary language and save it as a structured recipe or draft.
3. Ask for recommendations using time, ingredients, cuisine, dietary suitability, dish type, or mood.
4. Send a fridge or pantry photograph and receive three recommendations grounded in confirmed visible ingredients.
5. Rate a cooked recipe independently by replying to the recipe message.
6. Correct a classification or fill in a missing detail by replying in ordinary language.
7. Query the same stored recipes from Codex or Claude Code through MCP.

Example requests:

- “Something cozy and under 45 minutes.”
- “We have salmon, cabbage, and carrots. What can we make?”
- “Show me vegetarian Thai soups.”
- “Something light that we both like.”
- “Save this: tuna salad with tomato, quinoa, cucumber, arugula, and seeds. Need to season the tuna.”
- “That one takes about 30 minutes, not unknown.”

---

## 4. Explicit Non-Goals for the MVP

- A consumer SaaS product
- A custom web or mobile interface
- Monitoring Alex and Sam’s existing private WhatsApp conversation
- A WhatsApp Business sender, public webhook, or tunnel
- Bot-initiated messages (the bot only replies to messages in the group)
- Automated recipe discovery or crawling
- A permanently accurate pantry with quantities and expiration dates
- Nutritional analysis or medical claims
- Meal planning or calendar integration
- Embeddings or a vector database
- Multiple runtime models or automated model routing
- A fully autonomous taxonomy
- A raw JSON-RPC implementation of the MCP protocol

The implementation uses the official Python MCP SDK. Learning comes from designing and observing explicit tools, schemas, transports, state, and client behavior rather than recreating protocol plumbing.

---

## 5. User and Channel Model

### Telegram household group

Alex and Sam use their personal Telegram accounts. A dedicated bot is created through BotFather. One private Telegram group contains exactly three members: Alex, Sam, and the bot. The bot’s privacy mode is disabled so it receives every message in the group.

- Both members see every save, recommendation, and confirmation.
- Every Telegram message carries the sender’s numeric user ID, so ratings, dislikes, and corrections remain attributable to the correct person.
- The bot accepts messages only from allowlisted Telegram user IDs and only in the allowlisted group chat ID. Messages from anyone else, in any other chat, are ignored and logged as rejected without content.
- Direct messages to the bot from an allowlisted member are treated as the same household with the same store, so either member can use the bot privately if they prefer.

The bot never sends a message that is not a reply to a message in the group. This keeps the interaction model simple and avoids notification design in the MVP.

### Optional save-only shortcut

An iOS Shortcut in the share sheet may post a URL to a local `POST /save` endpoint on the Mac mini reachable only over Tailscale. This is a save-only path that complements the group. It is optional and is not required for any MVP gate.

### Existing WhatsApp history

The existing shared WhatsApp recipe conversation is imported using WhatsApp’s chat-export capability. The application extracts, canonicalizes, and deduplicates recipe links from the exported text. The import is idempotent by canonical URL, so the export can be repeated (for example monthly) to catch links the household forgot to send to the bot. The application does not read WhatsApp Desktop or the WhatsApp Business API.

Each imported recipe records `added_by_member_id` from the export sender name when the name maps to a configured member.

### Deferred: WhatsApp as a live channel

A WhatsApp Business sender can be registered later without Meta business verification for a reply-only bot, but it requires a Meta Business Portfolio, a public webhook, a tunnel, per-message cost, and a 24-hour reply window. Section 23 records this as a deferred decision. Because interfaces are thin, adding it means a second adapter, not a redesign.

---

## 6. Simplified Architecture

The architecture diagram, the decisions that shape the code and the layers are in [ARCHITECTURE.md](../../ARCHITECTURE.md).

---

## 7. Single-Model Baseline

Phase 1 uses one hosted multimodal model for every semantic task:

- Telegram intent interpretation
- MCP tool selection
- ingredient normalization
- recipe categorization
- mood and preference interpretation
- fridge and pantry image understanding
- user-facing response composition

This does not mean one enormous prompt or exactly one API call per user interaction. It means one model/provider establishes the baseline before any task-specific model substitution.

Ordinary Python and SQL handle:

- URL validation and canonicalization
- JSON-LD parsing
- duplicate detection
- dietary compatibility rules
- hard filtering
- recommendation scoring
- household authorization
- persistence and audit history

### Model-efficiency rules

- Perform recipe classification once at ingestion, not during every query.
- Use one structured classification call after deterministic recipe extraction.
- Cache ingestion by canonical URL and content hash.
- Cache model outputs by input hash, prompt version, and model version.
- Use strict structured outputs validated with Pydantic.
- Keep MCP results compact; return three recommendations by default.
- Do not send full recipe instructions when metadata and ingredients are sufficient.
- Record model, prompt version, latency, token use, validation failures, and user corrections.
- Do not add embeddings unless structured filtering proves inadequate.

### Conversation state

The Telegram host keeps a short per-chat context so follow-ups work without re-explaining:

- the last 10 turns or 30 minutes, whichever is smaller, passed to the model as prior context;
- the last result list shown in that chat (recipe IDs in display order) for ordinal references such as “the second one”;
- any pending confirmation (photo ingredients, recipe draft).

This state lives in `pending_interactions` (Section 15), not in the model. Anything older is dropped.

---

## 8. Recipe Sources

### 8.1 NYT Cooking URL

The application:

1. resolves redirects and removes tracking parameters;
2. validates the final hostname and recipe path;
3. checks for an existing canonical URL;
4. fetches schema.org JSON-LD over plain HTTP;
5. uses authenticated Playwright only if the JSON-LD is absent or incomplete;
6. extracts title, ingredients, yield, and time;
7. categorizes the structured recipe;
8. stores the metadata and NYT deep link;
9. returns a Telegram confirmation; and
10. classifies the recipe with one brain turn and edits that confirmation in place (Section 10).

NYT authentication is a one-time interactive login in the dedicated Playwright browser profile on the Mac mini. The session persists locally; no NYT password is stored. `make doctor` reports when the session has expired.

### 8.2 Personal recipe or recipe idea

Informal text is converted into a structured draft without inventing missing facts.

Input:

> Tuna salad with tomato, quinoa, cucumber, arugula and seeds. Need to season the tuna.

Expected draft:

```yaml
title: Tuna Quinoa Salad
ingredients:
  - tuna
  - tomato
  - quinoa
  - cucumber
  - arugula
  - seeds
dietary_suitability:
  - pescatarian
dish_type:
  - salad
primary_ingredients:
  - tuna
character:
  - light
  - fresh
total_minutes: null
notes:
  - Season the tuna before assembling
status: draft
```

The application must leave preparation time unknown and must not invent a seasoning. Alex or Sam can later update the recipe naturally (“that takes about 30 minutes”), which routes through `correct_recipe`.

### 8.3 Existing WhatsApp history

A CLI import command accepts an exported WhatsApp text file, extracts supported recipe links, deduplicates them, and creates an import report. Imported recipes are categorized through the same service used for new recipes.

The parser must handle both iOS and Android export formats (date format, bracket style, attachment placeholders). It is written against a redacted sample export stored in `tests/fixtures/`, never against the real export.

### 8.4 Unsupported links

Links that are not NYT Cooking recipe URLs (for example Bon Appétit, Serious Eats, Instagram) are stored with `source_type: other`, the canonical URL, and the page title if it can be fetched without authentication. They are not categorized in the MVP, are excluded from recommendations, and are listed separately in the import report so the household can see what the collection contains. Supporting additional recipe sites is a deferred decision.

---

## 9. Progressive Categorization

The initial taxonomy supports observed product questions without attempting to model every culinary attribute.

| Facet | Initial examples | Determination |
|---|---|---|
| Dietary suitability | vegan, vegetarian, pescatarian, omnivore | Ingredient flags plus validation rules |
| Cuisine | Thai, Italian, Indian, Japanese, Korean, Chinese, Vietnamese, Mexican, Mediterranean, American, French, other | Model, controlled values |
| Dish type | soup, salad, curry, stew, pasta, roast, stir-fry, sandwich, rice dish, noodle dish, other | Model, controlled values |
| Meal/course | breakfast, lunch, dinner, starter, dessert, snack | Model when relevant |
| Primary ingredient | salmon, tuna, chicken, tofu, legumes | Ingredients plus model; drives the `main_ingredient` filter |
| Total time | numeric minutes or unknown | Parsed from source |
| Effort | quick, weeknight, weekend, project | Time plus model |
| Character | bright, fresh, light, cozy, rich, spicy | Model |
| Cooking method | no-cook, roast, bake, grill, braise, pressure cook | Model when useful |
| Health orientation | light, balanced, rich | Explicitly heuristic, not nutritional advice |

### Dietary validation

Store ingredient-presence flags such as:

- `contains_meat`
- `contains_fish`
- `contains_shellfish`
- `contains_dairy`
- `contains_egg`

Flags are derived deterministically from each ingredient's name by lexicon and belong to the shared `ingredients` row. Every food named on a line becomes its own ingredient, so "chicken thighs, or shrimp" contributes both meat and shellfish; alternatives count. A person can correct an ingredient's food types for one recipe (`correct_recipe` `field_updates.food_types`); that override is stored per recipe in `recipe_ingredient_food_types` and never changes the shared row. A recipe's food types are the union over its ingredients and are reported as `contains`.

Dietary suitability *as written* counts every option on every line. Separately, the rules derive the stricter diets a recipe **can be made** through choices the recipe itself states, and nothing else:

- an "or" between foods on one line ("1 quart chicken or vegetable broth"): an option counts only when it names a recognised food, so "Mexican or Guatemalan chorizo" is not a choice;
- a line the author marks as optional ("optional", "if desired") or uses as a garnish ("for serving", "for topping", "to garnish"), which may be left out; a garnish list with several "or"s is left out as a whole rather than picked from;
- food types a line carries outside its stated options always stay.

Each "can be made" diet records its swaps ("use vegetable broth", "leave out parmesan"), preferring a stated option over leaving a line out. It respects per-recipe food-type corrections and is recomputed from the stored lines, so it needs no storage of its own.

Use rules to validate dietary suitability:

- Vegan: none of the above ingredients
- Vegetarian: no meat, fish, or shellfish
- Pescatarian: no meat; fish and shellfish permitted
- Omnivore: unrestricted

The model proposes classifications, but deterministic rules reject obvious contradictions. Nobody sets dietary suitability directly: it changes only when ingredients or their food types are corrected. After a parser or lexicon change, `make refresh-dietary` re-derives ingredients and dietary suitability for stored recipes without touching any other facet.

### Categorization records

Each classification stores:

- facet and value
- source: parsed, rule, model, or user
- confidence
- model version
- prompt version
- confirmation status
- created and updated timestamps

User-confirmed corrections take precedence over model output.

### Confidence threshold

The model returns a confidence in `[0, 1]` per facet. A classification with confidence at or above `CLASSIFICATION_CONFIDENCE_THRESHOLD` (default `0.8`, set in `.env`) is saved as-is. Below that it is saved but flagged for review, appears in the review report, and is marked in the Telegram confirmation with a `?` so the household knows it is a guess. The threshold is a single tunable, not a per-facet setting, until real data shows a need.

### Staples

`is_staple` on `ingredients` is seeded from `evals/recipes/staples.yaml`, a short committed list (oil, salt, pepper, garlic, onion, common spices, flour, sugar, butter, stock). The household can edit the list; changes are applied by `make categorize`. Staples are excluded from “missing ingredient” counts in ranking.

### Taxonomy growth

The model cannot silently create permanent categories. If no value fits, it returns `other` plus a proposed value. New values are added only after review or repeated evidence from real recipes and queries.

The proposed value is kept next to `other`, whether a model, an agent or a person supplied it. A person’s correction to a value outside the vocabulary is stored the same way rather than dropped. When the vocabulary grows, `recipe-mcp refresh-taxonomy` (`make refresh-taxonomy`) moves every stored `other` whose proposed value is now in the vocabulary onto that value and clears the proposal. No model is involved, user-confirmed values stay user-confirmed, and running it twice changes nothing. It then lists the proposed values still parked under `other`, with a recipe count for each, per facet, which is the evidence for the next addition. `ARGS=--dry-run` reports without writing.

Chinese and Vietnamese were added to the cuisine list on that basis (household use). Changing a vocabulary list changes the wording of every prompt that lists it, so those prompt versions are bumped with it.

---

## 10. Early Categorization Workflow

The categorization capability is part of the MVP, not a later add-on. It is a controlled workflow powered by the baseline model rather than a separate autonomous agent.

```text
WhatsApp export or newly saved recipe
                |
                v
       deterministic extraction
                |
                v
    structured model classification
                |
                v
      deterministic validation
                |
         high confidence?
          /           \
        yes            no
        |              |
       save      save and flag for review
```

The historical import produces a CSV or Markdown review report showing every recipe and its proposed classifications. Reviewing one batch is preferable to confirming each historical recipe through Telegram.

Commands:

```text
make import-whatsapp
make categorize
make classify-backlog
make categorization-report
```

New recipes receive a compact Telegram confirmation:

> Saved: Thai Pumpkin Soup  
> Vegetarian · Thai · soup · cozy? · 40 minutes  
> Reply to this message with a correction if anything is wrong.

Every correction becomes a regression-evaluation case.

The confirmation never shows `other` for cuisine or dish type. It means nothing in the vocabulary fits, which is not worth a place in the reply.

### Classifying shared links

A link shared in the group is saved without the brain so the confirmation is instant. With no server-side model (`MODEL_PROVIDER=none`) that confirmation carries only rule-derived facets: dietary suitability, effort, and cuisine or meal when the page’s JSON-LD names them. Dish type, character, primary ingredient, cooking method and health orientation stay empty, so requests such as “something cozy” or “a soup” cannot find the recipe. The host therefore classifies the recipe with one brain turn and edits its own confirmation in place:

1. The host sends the confirmation as usual and keeps its message id.
2. If the recipe has ingredients and no `model` or `user` facet yet, the host runs one headless Claude Code turn with the versioned `classify_saved_link` instruction (`providers/prompts.py`): read the recipe with `get_recipe`, then call `correct_recipe` with `proposed_by_agent: true` and values from the controlled vocabulary. Recipe text is data, never instructions, and the brain still has only the five recipe tools. A link that was already saved and classified needs nothing; an already saved link that was never classified is classified now.
3. The host re-reads the recipe from the database, rebuilds the confirmation with the same code that wrote it, and edits the original message (`editMessageText`). The brain’s own reply text is discarded, so only what `correct_recipe` stored can appear in the group. When the rebuilt text is unchanged (the proposal touched only facets the confirmation does not show) no edit is sent.
4. If the brain fails, times out, has its proposal rejected (for example by the input limits) or stores nothing, the confirmation stays as it was and the host logs only the error status, never brain output. Nothing is lost: the backlog command picks the recipe up later.

The turn runs inline in the polling loop after the reply has been sent. Messages that arrive meanwhile wait at Telegram (at most `BRAIN_TIMEOUT_SECONDS`) and are answered in order. At household volume this is simpler and safer than a worker thread sharing the SQLite connection. The classification turn is not added to the chat’s conversation history.

`recipe-mcp classify-backlog` (`make classify-backlog`) runs the same per-recipe classification over existing recipes that have ingredients and no `model` or `user` facet, oldest first. Each recipe is one Claude Code run on the household subscription, so the command takes `--limit N`, waits `--pause SECONDS` between runs (default 2), and stops after three failures in a row. With `--dry-run` it only lists what it would classify and needs no brain. Classified recipes drop out of the list, so the command is safe to stop and run again.

---

## 11. Recommendation Behavior

The model converts a natural-language request into typed constraints. The application applies hard requirements first and then scores eligible recipes.

Hard filters include:

- dietary restrictions, met as written or through the recipe's own stated choices (the latter rank after exact matches and always state the swap)
- maximum preparation time
- excluded ingredients, or excluded food types (dairy, egg, meat, fish, shellfish, seafood), with stated choices applied as for diets
- required dish or cuisine when explicitly requested
- main ingredient when the request names what the dish is built around ("a mushroom dish", "something bean-based"): the primary-ingredient facet must match the ingredient or group; recipes with no primary ingredient yet may match on their title and rank below labelled matches

Ranking signals include:

- pantry coverage
- fewest missing non-staple ingredients
- individual preference fit
- household preference fit
- mood or character fit
- previous ratings
- recent repetition

The model explains results but does not decide which recipes exist or fabricate database matches.

Default output is three meaningfully different recommendations, each containing:

- title
- time
- key classifications, with the food types behind the dietary label
- ingredients available and missing
- reason it fits
- original source link

The full NYT recipe remains on NYT Cooking. The Telegram response is the summary and navigation surface.

### Message format constraints

- Telegram messages are limited to 4,096 characters. Three recommendations with links must fit in one message; the composer truncates reasons before dropping a recommendation.
- Use plain text with Telegram’s HTML parse mode for bold titles and links only. No tables, headers, or nested formatting.
- NYT deep links are sent as full `https://cooking.nytimes.com/recipes/...` URLs so iOS opens them in the native NYT Cooking app.
- Each recommendation is sent as one message per recipe when the user has asked to rate or refer to individual results; otherwise one combined message. The result order is stored for ordinal references either way.

---

## 12. Household Preferences and Feedback

Each member rates recipes independently by replying to the recipe message:

- ❤️ = favorite; definitely cook again
- 👍 = liked it
- 👎 = do not recommend again

The reply’s `reply_to_message_id` identifies the recipe deterministically. Native Telegram reactions on the bot’s messages are also accepted. An unreplied emoji or natural-language rating resolves against the last result list in that chat.

“Something we both like” means:

- both members have explicitly rated the recipe positively; or
- for an uncooked recipe, the system labels it as “likely to suit both” based on previous preferences.

Household ranking emphasizes the lower individual preference score so that one person’s enthusiasm does not erase the other person’s dislike.

Natural-language feedback is supported:

- “We both loved this.”
- “I liked it, but Sam didn’t.”
- “Don’t recommend this to me again.”

When one member reports the other member’s opinion, the feedback row is stored against the reported member with `reported_by_member_id` set, so the distinction is auditable.

---

## 13. Photo and Voice Input

### Photo

1. A fridge or pantry photo arrives in the Telegram group.
2. The application downloads it through the Bot API `getFile` endpoint to an approved temporary directory.
3. The baseline model returns ingredient candidates with confidence.
4. The assistant asks for confirmation of uncertain items.
5. Confirmed ingredients are passed to `recommend_recipes`.
6. The raw image is deleted by default.

The MVP treats visible ingredients as context for the current request. It does not attempt to maintain a permanently accurate pantry.

### Voice

- iPhone dictation arrives as text and requires no transcription service.
- Telegram voice-note transcription is a fast follow after text and photo inputs work.

---

## 14. MCP Tools

The initial server exposes five user-facing tools.

### Member identity

Every tool that writes accepts an optional `member: str | None` (a configured member key such as `alex` or `sam`). The Telegram host always sets it from the sender’s user ID. For Codex and Claude Code the server falls back to `DEFAULT_MEMBER` from `.env`, so a personal MCP configuration on Alex’s machine acts as Alex without passing the parameter on every call. Read-only tools accept `member` to personalize ranking and default to the household view when absent.

### `save_recipe`

Accepts either a supported recipe URL or an informal recipe description. It extracts, normalizes, categorizes, validates, and stores the recipe. Duplicate URLs update or return the existing record rather than creating duplicates.

**Inputs:** `input: str`, `notes: str | None`, `member: str | None`  
**Returns:** stored recipe or structured draft, classifications with confidence and review flags, warnings  
**Behavior:** idempotent for canonical URLs

### `recommend_recipes`

Returns up to three recipes matching typed constraints and available ingredients.

**Inputs:** dietary requirements, cuisine, dish type, `main_ingredient` (an ingredient or a group: beans/legumes, fish, seafood, shellfish, meat, poultry), mood/character, maximum time, available ingredients, maximum missing ingredients, `member: str | None`  
**Returns:** ranked matches with reasons, `contains` food types, `adapted_for` and `diet_swaps` when a recipe meets the requested diet only through its stated choices, missing ingredients, and source links  
**Behavior:** read-only

### `get_recipe`

Returns stored metadata, ingredients (each with its food types and whether a person corrected them), classifications, `contains` food types, `can_be_made` (stricter diets reachable through stated choices, with swaps), feedback summary, personal notes, and source link.

**Inputs:** `recipe_id`  
**Returns:** complete stored recipe record  
**Behavior:** read-only

### `rate_recipe`

Records individual or explicitly reported household feedback.

**Inputs:** `recipe_id`, sentiment, `member: str | None`, `on_behalf_of: str | None`, optional notes  
**Returns:** updated individual and household feedback summary

### `correct_recipe`

Applies a user correction to a stored recipe. Corrections to a facet override the model classification and are stored with `source: user` and `user_confirmed: true`. Corrections to recipe fields (`total_minutes`, `title`, `notes`, an added or removed ingredient) update the record and re-run dietary validation. `field_updates.food_types` maps an ingredient in the recipe to its complete list of food types (`[]` for none); it applies to that recipe only and re-runs dietary validation.

**Inputs:** `recipe_id`, `facet_corrections: dict[str, list[str]] | None`, `field_updates: dict | None`, `member: str | None`  
**Returns:** updated record and a list of what changed  
**Behavior:** every call appends a regression case to the private evaluation set

### Input limits

The write tools reject oversized values rather than truncating them, so a recipe is never stored silently incomplete. The Telegram brain fills these arguments from household messages and web pages, so the limits bound what a crafted message can make it store. Errors name the field and the limit, never the value. The limits live in `domain/limits.py`:

| Value | Limit |
|---|---|
| `save_recipe` `input` (URL or description) | 20,000 characters |
| Title | 300 characters |
| Ingredients | 100 lines of up to 1,000 characters |
| Notes | 20 notes of up to 2,000 characters (`rate_recipe` notes: one note) |
| Servings | 100 characters |
| Classifications and facet corrections | 20 facets, 20 values each, 100 characters per value |

`correct_recipe` checks every field before writing any of them, so a rejected correction changes nothing. Recipes read from NYT JSON-LD are not subject to these limits.

### Internal application operations

The application also contains internal operations used by ingestion and administration:

- `categorize_recipe`
- `categorize_uncategorized_recipes`
- `review_low_confidence_classifications`
- `import_whatsapp_export`
- `refresh_dietary` (re-parse stored ingredient lines and re-run dietary rules)
- `classify_backlog` (one brain turn per unclassified recipe; Section 10)
- `refresh_taxonomy` (move stored `other` values onto newly added vocabulary; Section 9)

These are reachable from the CLI and do not need to be exposed as general MCP tools in the first release.

---

## 15. Minimum Data Model

### `households`

- id
- name
- created_at

### `members`

- id
- household_id
- member_key (`alex`, `sam`)
- display_name
- telegram_user_id
- whatsapp_export_name (for backfill attribution)
- normalized_phone_number (nullable; reserved for a later WhatsApp adapter)
- role
- active

### `recipes`

- id
- household_id
- source_type: `nyt`, `personal`, or `other`
- canonical_source_url
- title
- servings (parsed metadata only)
- total_minutes
- notes
- status: `draft` or `complete`
- content_hash
- added_by_member_id
- added_at
- updated_at

### `ingredients`

- id
- canonical_name
- category
- is_staple
- contains_meat, contains_fish, contains_shellfish, contains_dairy, contains_egg (lexicon defaults, shared)

### `recipe_ingredient_food_types`

A person's per-recipe correction of an ingredient's food types.

- recipe_id
- canonical_name
- contains_meat, contains_fish, contains_shellfish, contains_dairy, contains_egg
- member_id
- created_at

### `recipe_ingredients`

- recipe_id
- ingredient_id
- raw_text
- quantity
- preparation

### `recipe_facets`

- recipe_id
- facet
- value
- source
- confidence
- model_version
- prompt_version
- user_confirmed
- needs_review
- created_at
- updated_at

### `recipe_feedback`

- id
- recipe_id
- member_id
- reported_by_member_id (nullable)
- sentiment
- notes
- cooked_at
- created_at

### `model_runs`

- id
- task
- input_hash
- provider
- model
- prompt_version
- latency_ms
- input_tokens
- output_tokens
- validation_status
- created_at

### `pending_interactions`

Short-lived per-chat state:

- chat_id
- kind: `recent_results`, `photo_confirmation`, `draft_confirmation`, `turn_history`
- payload (JSON)
- expires_at

Rows are deleted on expiry. This table is the only place conversation state is stored.

---

## 16. Repository Structure

The repository tree is in [ARCHITECTURE.md](../../ARCHITECTURE.md). The rules enforced in review are in [AGENTS.md](../../AGENTS.md).

### Local environment and secret handling

Repository setup must create a local `.env` by copying `.env.example`. The local `.env` is the only default location for development secrets and machine-specific values. It must be ignored by Git before any credentials are added.

`.env.example` is committed and contains variable names, comments, and safe blank placeholders only:

```dotenv
APP_ENV=development
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///data/recipes.db

MODEL_PROVIDER=openai
MODEL_NAME=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

CLASSIFICATION_CONFIDENCE_THRESHOLD=0.8
DEFAULT_MEMBER=

TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_GROUP_CHAT_ID=

SHORTCUT_ENDPOINT_ENABLED=false
SHORTCUT_BIND_ADDRESS=

NYT_BROWSER_PROFILE_PATH=.private/nyt-browser-profile
WHATSAPP_EXPORT_PATH=.private/whatsapp-export.txt
PRIVATE_EVALS_PATH=.private/evals
TEMP_MEDIA_DIR=.private/tmp-media
```

Only the key for the selected baseline provider is required. `TELEGRAM_ALLOWED_USER_IDS` is a comma-separated list of numeric Telegram user IDs mapped to members in a small committed-free `.private/members.yaml`. Actual IDs, tokens, keys, cookies, and credentials must never appear in `.env.example`, prompts, logs, test fixtures, documentation, or commits.

The root `.gitignore` must include at least:

```gitignore
.env
.env.*
!.env.example
.private/
data/*.db
data/*.db-*
playwright/.auth/
test-results/
```

Configuration behavior:

- `make setup` creates `.env` from `.env.example` only when `.env` does not already exist; it must never overwrite an existing local file.
- Offline tests, linting, type checking, and fixture-based evaluations run without API keys or external-service credentials.
- Application startup validates only the variables required for the selected command or integration and reports missing variable names without printing values.
- Live model, NYT, Telegram, and photo smoke tests are opt-in and fail clearly when their required configuration is absent.
- CI uses mocked providers and isolated test settings. It must not depend on the developer's local `.env`.
- A secret scan runs in CI and before public release.

### MCP client configuration

`save_recipe` and `correct_recipe` call the model, so the MCP server process itself needs the provider key. The committed Codex and Claude Code configuration examples launch the server with `uv run --env-file .env recipe-mcp serve` from the repository root, so the key is read from the local `.env` and never appears in the client configuration file.

### Repository user onboarding

The repository must support a first-time user who did not build the application. The README must provide a tested, copy-and-paste setup path from a fresh clone to a successful local MCP recommendation without requiring Telegram, NYT authentication, or access to Alex and Sam's private data.

The default onboarding path is:

```text
clone the repository
→ run make setup
→ initialize the SQLite database
→ load synthetic demonstration recipes
→ configure Codex or Claude Code as an MCP client
→ run offline tests
→ request one sample recommendation through MCP
→ optionally choose a live model and add its API key only to local .env
→ optionally configure personal recipes, NYT, and Telegram
```

The README must separate four setup levels:

1. **Core local setup:** prerequisites, clone, dependency installation, `.env` creation, database initialization, synthetic sample data, MCP-client configuration, tests, and a first successful query.
2. **Personal household setup:** private WhatsApp export placement, household members and Telegram user IDs, recipe backfill, and categorization review. No private household data is included in the repository.
3. **Optional live integrations:** model credentials, interactive NYT browser authentication, Telegram bot creation and group setup, Mac mini deployment, and live smoke tests.
4. **Contributor setup:** architecture boundaries, development commands, testing layers, eval workflow, migration rules, prompt versioning, secret scanning, and pull-request expectations.

Onboarding requirements:

- State supported macOS and Python versions and list prerequisite installation commands.
- Explain the difference between `.env` and `.env.example`, and warn users never to commit `.env`.
- Provide tested Codex and Claude Code MCP configuration examples using local paths or clearly marked placeholders.
- Include synthetic demonstration recipes and expected results so the first run does not depend on an NYT subscription or private export.
- Provide a health-check or diagnostic command that verifies configuration, database access, MCP startup, NYT session validity, Telegram token validity, and fixture availability without exposing secret values.
- Mark every external integration as optional for the core local demonstration.
- Include troubleshooting for missing environment variables, unavailable model credentials, MCP connection failures, database initialization, Playwright authentication, and Telegram polling errors.
- Never instruct users to paste API keys, credentials, user IDs, or exported chats into an AI conversation or commit them to Git.

The setup is considered complete when a fresh-clone user can run the offline suite, connect one supported MCP client, and retrieve three recommendations from synthetic sample recipes. Live NYT and Telegram configuration have their own later smoke-test gates and are not prerequisites for this first-run success.

Standard commands:

```text
make setup
make doctor
make demo
make test
make lint
make typecheck
make eval
make smoke
make import-whatsapp
make categorize
make categorization-report
make serve-telegram
make install-daemon
```

---

## 17. Testing Strategy

### Unit tests

- URL validation and canonicalization
- duplicate handling
- dietary rules
- ingredient aliases and staples
- ingredient-line parsing, including every food on a line and look-alike words
- main-ingredient matching and groups
- "can be made" diets: stated choices only, never inferred swaps
- recommendation scoring
- household authorization (Telegram user and chat allowlists)
- feedback aggregation, including reported-on-behalf-of feedback
- ordinal reference resolution against a stored result list

### Contract tests

- MCP input and output schemas for all five tools
- model structured-output schemas
- database repository interfaces
- Telegram message and reply parsing
- WhatsApp export parsing for iOS and Android formats

### Integration tests

- static NYT JSON-LD fixtures
- mocked model responses
- temporary SQLite database
- complete save-and-query vertical slice
- save, correct, and re-query slice
- food-type correction survives `refresh-dietary` and affects only its recipe
- historical export parsing and idempotent re-import

Normal CI must not require NYT, Telegram, Playwright, or a live model.

### Live smoke tests

Run manually or on demand:

- live model classification
- authenticated NYT import
- Telegram inbound message and reply in the household group
- photograph processing
- Codex and Claude Code MCP connections

---

## 18. Initial Evaluation Set

Use actual saved recipes rather than constructing a large theoretical benchmark.

### Public and private evaluation data

The repository ships a synthetic evaluation set under `evals/`. The household’s real evaluation set (real recipes, real queries, approved results, and every correction captured by `correct_recipe`) lives under `.private/evals/` and is never committed. `make eval` runs the synthetic set always and the private set when the path exists, reporting them separately.

Seed data:

- 15–25 representative recipes from the existing WhatsApp export (private)
- the personal tuna-quinoa-salad example (public)
- approximately 10 realistic recommendation requests
- two or three fridge/pantry images when photo support is added (private)

Initial query set:

1. Something cozy under 45 minutes.
2. A healthy salmon dinner.
3. Vegetarian Thai food.
4. A soup using cabbage.
5. Something light but satisfying.
6. Dinner using the ingredients visible in this photograph.
7. Something both household members like.
8. A recipe requiring no more than two missing ingredients.
9. Something quick that has not been cooked recently.
10. A richer weekend meal.

Metrics:

- ingredient extraction accuracy
- multi-label categorization precision and recall
- dietary-classification accuracy
- query-constraint extraction accuracy
- correct MCP tool selection
- expected useful recipe in the top three
- image ingredient precision and recall
- user correction rate
- latency and token use

Dietary contradictions have near-zero tolerance. Subjective facets such as “cozy” are evaluated through human review and observed usefulness.

---

## 19. Roadmap

This is the backlog. New ideas go here with a tag instead of being built unasked. An idea is written into the body of this spec before it is built, and then leaves this section.

- `follow-up`: agreed and wanted, next in line.
- `idea`: worth exploring, needs a decision before any work.
- `ops`: running and maintaining the always-on Mac, not product features.
- `deferred`: consciously parked. These are listed in Section 23.

### How it was staged

The MVP was built in four gated stages, all done. Stage 0 collected the seed and acceptance data (the WhatsApp export, the first query set, the tuna-salad fixture). Stage 1 built the offline core: schema, five MCP tools, importers, categorization, recommendation, corrections, tests, evals and CI. Stage 2 added live NYT ingestion and the idempotent WhatsApp backfill. Stage 3 added the Telegram group, allowlists and member mapping, and the launchd daemon that survives a reboot. Git history holds the original stage plans.

### Next stages

**Photo input** `idea`. "What can we make from this fridge photo?" (Section 13). Telegram `getFile`, temporary storage under `.private/`, ingredient extraction by the brain, confirmation of uncertain items, then `recommend_recipes`. Raw images are deleted after processing. Gate: a fridge or pantry photo produces three recommendations based only on confirmed ingredients.

**Real-use pilot** `follow-up`. Use the assistant for about two weeks or 20 to 30 recommendation requests. Review failed searches, corrections, selected recipes and missing categories. Gate: evidence decides whether persistent pantry state, shopping lists, voice notes, a WhatsApp channel or more taxonomy are justified.

**Multi-model experiment** `idea`. Freeze the baseline. Substitute one task at a time with smaller hosted or local models: ingredient normalization, recipe categorization, query interpretation, photo recognition. Compare quality, latency and cost on the same approved evaluation set. Never change prompts, taxonomy and models at the same time.

### Follow-ups

**Fill in recipes linked from other sites** `follow-up`. Only NYT Cooking links are read. Links to other sites are saved as `other` stubs with a title and URL only, so cuisine, dish type and ingredient filters never match them. A sample of saved non-NYT links showed only about one in ten pages carried standard recipe data. About half loaded with none, about a third refused automated requests or were dead, and videos and social posts never carry it. Three levels:

1. Simple, planned first. Parse Recipe JSON-LD from any site. Add a generic fetcher that reuses the title fetcher's protections (public addresses only, checked on every redirect, size cap), fall back to today's stub, and add a backfill command that retries existing stubs. Prerequisite: the title fetcher checks a host's addresses and then connects in a second DNS lookup, so a hostile DNS server could answer differently (DNS rebinding). Before fetching whole pages, connect only to the checked address, keeping the host name for TLS and the `Host` header, on every redirect.
2. Smart. Have the brain extract recipes from pages without structured data. This reopens a door the security review closed, because the bot's Claude Code has no web access. A safe design has the server fetch and strip the page to plain text, pass only that as clearly marked untrusted data, and store a `needs_review` draft. Needs its own spec and security pass.
3. Sites that refuse automated requests. Only a signed-in browser per site, as with NYT. Not worth it until a specific site matters.

Videos and social posts stay stubs, classified from the title and marked `needs_review`. This lifts the "recipe sites beyond NYT Cooking" deferral, so Section 23 changes first. Open question: is level 2 worth the extra attack surface once level 1 is in daily use?

**Warn before the Claude Code token expires** `follow-up` `ops`. `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` lasts one year. When it lapses the bot only says "Sorry, I couldn't work that out." Record the creation date in `.env`, have `make doctor` warn 30 days ahead, and make the brain's 401 produce a clear log line.

**Free-form household tags** `follow-up`. The controlled taxonomy cannot hold personal labels ("Sam's birthday", "freezer-friendly", "guests"). Spec first, then a tags table, `save_recipe` and `correct_recipe` support, and a `tag` filter on `recommend_recipes`.

### Ideas

**Learn from the household over time** `idea`. Today the assistant adapts only through deterministic signals: ratings change ranking, recent cooking is pushed down, corrections are permanent. The brain starts fresh on every message. In order of value: remember stated preferences as hard rules per member ("no pork on weeknights"), applied by the ranking filters; feed recent corrections to the brain as examples when it classifies; grow the taxonomy from repeated `other` proposals with a review step; record which recommendation was chosen and tune ranking weights. Open question: which of these would the household notice day to day?

**Chat with the recipes from the Claude app** `idea`. Longer conversations and planning in the Claude app, while Telegram stays the quick shared channel. Serve the MCP server over streamable HTTP behind authentication and a public address (for example a Cloudflare Tunnel, since Claude connects to custom connectors from the cloud), then add it once as a custom connector. Open questions: whose identity those writes use, whether Sam gets a connector, and which host.

**Linux or cloud hosting via systemd** `idea`. The daemon uses launchd, so the bot only runs on a Mac. A Linux box or a small cloud server (about $5 to $7 a month) would restart unattended after a power cut, where a FileVault Mac waits for its password. Needs a systemd unit beside the plist, setup docs, and moving `data/recipes.db`, `.env` and `.private/`. The NYT browser profile is the awkward part. Open question: is unattended recovery worth a monthly bill and data on a rented machine?

**Keep the recipes in Google Drive** `idea`. Drive stores files but runs nothing, and a live SQLite file in a synced folder can be corrupted. Realistic versions: a nightly read-only backup into Drive; a mirrored Google Sheet rebuilt after each change; or hosted Postgres if the server moves to the cloud. Open question: is the goal backup, sharing, or running without the Mac?

**Review recipes from Claude Code on the web** `idea`. Cloud sessions see only the repository, and the live database is deliberately not in Git. A nightly YAML export of every recipe into a private data repository, plus an import step for reviewed changes, would allow it. Or expose the MCP server to cloud sessions once the bot runs on a server. Open questions: is household data acceptable in a private GitHub repository, and how to avoid conflicts with the bot's writes.

**Offline export for the phone** `idea`. `recipe-mcp export` writes one searchable HTML or Markdown file to iCloud Drive or Google Drive, refreshed nightly. Read-only, no recommendations.

**Local model fallback brain (Ollama)** `idea`. If unattended use of the Claude subscription stops being an option, the bot needs a brain on the Mac itself. A second brain behind `BRAIN=ollama`, calling the same MCP server.

### Ops

**Log file naming** `ops`. The bot writes its log lines to `/Library/Logs/recipe-mcp/telegram.err.log`, and `telegram.log` stays empty. Either log to stdout or rename the paths so the obvious file is the useful one.

---

## 19A. Running on the Mac mini

The always-on Mac is the only runtime host. How to install, run, back up and restore it is in [deploy/README.md](../../deploy/README.md), and `make install-daemon` automates it where practical.

---

## 20. Security and Privacy

- Allowlist household Telegram user IDs and the group chat ID; ignore everything else.
- Validate final URLs after redirects.
- Restrict authenticated browsing to approved recipe domains.
- Use parameterized database access.
- Keep secrets in environment variables.
- Store local secrets and machine-specific configuration in `.env`, created from the committed `.env.example`.
- Exclude `.env`, `.private/`, browser profiles, WhatsApp exports, temporary media, private evaluations, backups, and local databases from Git, and verify the exclusions during preflight.
- Restrict temporary-image paths and delete images after processing.
- Never log cookies, session data, message contents, or raw photographs by default.
- Keep the MCP server local over stdio in the MVP.
- Bind the optional shortcut endpoint only to the Tailscale interface; never to `0.0.0.0`.
- Run dependency and secret scans before public release.
- Document that NYT access uses the household’s legitimate subscription and that the application retains deep links rather than republishing full instructions.

---

## 21. Public Release Checklist

The release checklist moved to the publish script work, where each box is ticked as the release is prepared. It is tracked with the factory's issues, outside this file, so this public spec does not carry a list that is never ticked.

---

## 22. Success Criteria

The experiment is successful when:

- existing WhatsApp recipe links can be imported and reviewed in a batch, and re-imported without duplicates;
- a new NYT link shared from the iOS app can be saved and categorized without manual data entry;
- an informal personal recipe is stored without invented details;
- both household members can query the same collection from one group;
- at least one of three recommendations is useful most of the time;
- dietary filters do not produce obvious violations;
- user corrections persist, override the model, and become regression cases;
- a fridge or pantry photograph produces grounded recommendations;
- Codex and Claude Code can call the same MCP tools;
- the service runs unattended on the Mac mini and survives a reboot;
- the repository can be installed and tested by someone who did not build it; and
- Phase 2 produces a repeatable comparison between the baseline and alternative models.

---

## 23. Deferred Decisions

Open ideas and agreed follow-ups that are not yet specified live in the Roadmap (Section 19). The decisions below are consciously parked.

- Whether to add a WhatsApp Business sender as a second channel after the pilot (requires Meta Business Portfolio, public webhook, tunnel, per-message cost, and the 24-hour reply window; no business verification needed for a reply-only bot)
- Whether remote MCP access from a laptop over Tailscale is worth the setup
- Whether additional recipe sites beyond NYT Cooking should be parsed and categorized
- Whether SQLite creates a real concurrency or operational limitation
- Whether persistent pantry state is useful enough to justify freshness and quantity management
- Whether shopping-list generation is used frequently enough to add as an MCP tool
- Whether voice-note transcription belongs in the application
- Which individual tasks merit local-model replacement after baseline evaluation
- Whether to build the iOS Shortcut save endpoint: a share-sheet Shortcut posting a URL to a local `POST /save`, reachable only over Tailscale (Section 5). `adapters/shortcut/` is an empty stub and the `SHORTCUT_*` settings in `.env.example` do nothing yet
- Whether a private web reading interface is necessary beyond Telegram summaries and source links
- Whether the Telegram host needs rate limits or a daily budget on brain runs (today it handles one message at a time and only allowlisted members reach it)
