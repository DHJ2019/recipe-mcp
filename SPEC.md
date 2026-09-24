# Recipe MCP — Project Specification

**Author:** recipe-mcp contributors  
**Status:** Draft v3.5  
**Primary objective:** Learn MCP by building a useful shared household recipe assistant  
**Initial clients:** Telegram (shared household group), Codex, and Claude Code  
**Repository:** Private Git repository initially; public release after the checklist in Section 21  
**Runtime:** Python 3.13 on an always-on Mac mini  
**Names:** Alex and Sam are placeholders for the two household members throughout this document.

---

## 0. Changes in v3.5

- **Every food on an ingredient line counts.** A line that names more than one food ("2 chicken thighs, cut into cubes, or 8 shrimp") stores one ingredient per food, and the recipe carries every food type they need. Alternatives count: "chicken or vegetable stock" makes a recipe omnivore. Extra foods are named by the food word itself (`shrimp`, `cod`).
- **Food types are visible.** Recipes and recommendations report `contains` (meat, fish, shellfish, dairy, egg), the reason behind the dietary label; Telegram shows it next to the diet ("omnivore (meat, shellfish)").
- **People can correct an ingredient's food types for one recipe** through `correct_recipe` `field_updates.food_types` (e.g. `{"oyster mushroom": []}`). The correction overrides the lexicon for that recipe only, re-runs the dietary rules and becomes a regression case. Dietary suitability still cannot be set directly. New table `recipe_ingredient_food_types` (migration `0002`).
- **"Can be made" diets.** Besides the strict dietary label, a recipe can reach a stricter diet through choices its own ingredient lines state: an "or" between foods ("chicken or vegetable broth"), or a line marked optional or used as a garnish ("for serving", "for topping"). Nothing is inferred: a recipe that only says "chicken broth" is never offered as vegan. A dietary request returns exact matches first, then recipes that reach the diet through stated choices, each with `adapted_for` and `diet_swaps` ("vegan if you use vegetable broth"). `get_recipe` reports `can_be_made`.
- **A food type counts only when it is listed.** Nothing is assumed from a dish name: dumplings take their food type from a stated filling ("pork dumplings" is meat, "potsticker dumplings" has none), and mayonnaise and aioli are not egg unless egg is listed.
- **Excluding a food type.** `excluded_ingredients` accepts whole food types (dairy, egg, meat, fish, shellfish, seafood) as well as ingredients, so "nothing with egg" excludes egg noodles and mayonnaise, not only eggs. A food type counts only when an ingredient carrying it is listed: a recipe with pierogies is not an egg dish unless egg is on the list. Stated choices apply as for diets ("no dairy if you leave out parmesan").
- **`recommend_recipes` gains `main_ingredient`,** a hard filter on what the dish is built around: an ingredient ("mushroom") or a group (beans/legumes, fish, seafood, shellfish, meat, poultry). The primary-ingredient facet decides; a recipe with no primary ingredient yet falls back to its title and ranks below labelled matches.
- **`make refresh-dietary`** re-parses stored ingredient lines and re-runs the dietary rules after the parser or lexicons change. It rewrites only ingredients and `dietary_suitability`; `ARGS=--dry-run` lists the recipes that would change.
- Parser fixes found in the WhatsApp backfill: leading cut descriptors ("bone-in, skin-on chicken thighs"), packing phrases ("sardines packed in olive oil"), accented names ("crème fraîche"), and look-alike words (oyster mushrooms, butter beans, cream of tartar) no longer flagged as animal foods.

## 0a. Changes in v3.4

- **Claude Code is the brain.** No hosted model API is called by the application. Semantic work (interpreting a chat message, parsing an informal recipe, proposing classifications, composing a reply) is done by the MCP *client* agent: Claude Code or Codex when a person is at a terminal, and a headless `claude -p` run when a Telegram message arrives. The MCP server is fully deterministic and needs no API key. `MODEL_PROVIDER=none` is the default; `openai` and `fake` remain available for the Phase 2 comparison.
- `save_recipe` accepts structured fields (`title`, `ingredients`, `total_minutes`, `servings`, `classifications`) so an agent that has already parsed the text can save without a server-side model. Free text is still accepted when a model provider is configured.
- `correct_recipe` gains `proposed_by_agent`: with it set, facet values are stored as a model-grade proposal (`source: model`, `model_version: agent`) rather than a user-confirmed correction, and no regression case is written. This is how an agent classifies a recipe the server extracted from a URL.
- Recipes saved without any classification proposal are stored with rule-derived facets only and flagged `needs_review`; the server's instructions tell the agent to classify them.
- The Telegram host talks to the Bot API directly over HTTPS (`getUpdates` long polling, `sendMessage`), replacing the `python-telegram-bot` dependency named in v3.3. The host resolves ratings, reply-to references, ordinal references and time corrections deterministically and only invokes the brain for everything else.
- The brain contract: the host passes the member key, the last turns and the last result list; the agent must answer in plain text and end with a `RECIPES:` line listing the recipe ids it mentioned, which the host strips and stores as conversation state.
- New `.env` keys: `BRAIN` (`claude-code` or `none`), `CLAUDE_CODE_BIN`, `BRAIN_MODEL`, `BRAIN_TIMEOUT_SECONDS`, `BRAIN_MAX_TURNS`.
- Unattended use of a Claude subscription through `claude -p` is the household's own arrangement with Anthropic; the repository documents the setup and does not embed credentials. A local model (Ollama) remains the fallback brain if that arrangement changes.

## 0b. Changes in v3.3

- Telegram replaces WhatsApp as the MVP messaging channel. One shared Telegram group containing Alex, Sam, and the bot replaces two separate bot conversations.
- No public webhook or tunnel in the MVP. The Telegram bot uses long polling.
- The existing WhatsApp recipe conversation is still imported from a chat export, and the import is idempotent so periodic re-exports can be repeated.
- A WhatsApp Business sender is a deferred decision (Section 23), not an MVP dependency.
- New `correct_recipe` MCP tool so corrections work through the same interface as every other channel.
- Member identity for MCP clients, ordinal references (“the second one”), conversation state, staples, the confidence threshold, unsupported links, backfill attribution, private evaluation data, and message-length limits are now specified.
- New Section 19A covers running the service on the Mac mini.
- Unused schema fields (`diners`, `hands_on_minutes`) removed.

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

```text
Alex / Sam personal Telegram accounts
                 |
                 v
        Telegram Bot API (long polling; outbound only)
                 |
                 v
     Telegram agent host (Python, launchd service on Mac mini)
     - single hosted model
     - MCP client
     - per-chat conversation state
                 |
             stdio MCP
                 |
                 v
         Recipe MCP server
                 |
        shared application services
          /          |          \
         v           v           v
      SQLite     NYT fetcher    Model client
                 HTTP first     one provider
                 Playwright
                 fallback

Codex / Claude Code --------> Recipe MCP server over stdio
Optional iOS Shortcut ------> POST /save (Tailscale only)
```

### Architectural decisions

- One Python repository and one Python package
- SQLite in WAL mode for the personal, low-volume MVP
- A repository interface isolates persistence so Postgres can replace SQLite later if needed
- Telegram Bot API through `python-telegram-bot` using long polling; no inbound network exposure
- HTTP plus schema.org JSON-LD for the normal NYT fetch path
- Python Playwright with a persisted dedicated browser profile only when authentication is required
- One `ModelClient` interface with one hosted multimodal implementation in Phase 1
- MCP over stdio for local Codex and Claude Code clients
- The Telegram host maintains a local MCP client session and uses the same tool contracts
- The Telegram host and any MCP client each spawn their own MCP server process; SQLite WAL mode handles the resulting low-concurrency access

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
8. stores the metadata and NYT deep link; and
9. returns a Telegram confirmation.

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
| Cuisine | Thai, Italian, Indian, Japanese, Korean, Mexican, Mediterranean, American, French, other | Model, controlled values |
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
make categorization-report
```

New recipes receive a compact Telegram confirmation:

> Saved: Thai Pumpkin Soup  
> Vegetarian · Thai · soup · cozy? · 40 minutes  
> Reply to this message with a correction if anything is wrong.

Every correction becomes a regression-evaluation case.

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

### Internal application operations

The application also contains internal operations used by ingestion and administration:

- `categorize_recipe`
- `categorize_uncategorized_recipes`
- `review_low_confidence_classifications`
- `import_whatsapp_export`
- `refresh_dietary` (re-parse stored ingredient lines and re-run dietary rules)

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

```text
recipe-mcp/
├── src/recipe_mcp/
│   ├── domain/                 # recipes, dietary rules, ranking
│   ├── services/               # ingestion, categorization, recommendation, corrections
│   ├── adapters/
│   │   ├── mcp/                # MCP server and schemas
│   │   ├── telegram/           # bot host, long polling, MCP client session
│   │   ├── shortcut/           # optional POST /save endpoint (Tailscale only)
│   │   └── nyt/                # HTTP and Playwright import
│   ├── providers/              # single baseline ModelClient
│   ├── db/                     # repositories and migrations
│   ├── settings.py             # typed environment configuration and validation
│   └── cli/                    # import, review, doctor commands
├── migrations/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── fixtures/               # synthetic recipes, redacted export sample
├── evals/
│   ├── recipes/                # synthetic recipes and staples.yaml
│   ├── queries/
│   ├── images/
│   └── approved_results/
├── deploy/
│   ├── com.recipe-mcp.telegram.plist   # launchd daemon
│   └── README.md               # Mac mini setup
├── scripts/
├── .github/workflows/ci.yml
├── AGENTS.md
├── CLAUDE.md
├── Makefile
├── pyproject.toml
├── uv.lock
├── .env                        # generated locally; never committed
├── .env.example
├── .gitignore
├── .private/                   # ignored exports, browser profile, temporary media, private evals
├── README.md
├── SECURITY.md
└── LICENSE
```

### Repository rules

- `AGENTS.md` and `CLAUDE.md` point to the same canonical architecture and commands.
- No business logic in Telegram, shortcut, or MCP adapters.
- No direct model calls outside `providers/`.
- All configuration is loaded and validated through `src/recipe_mcp/settings.py`; application code must not read environment variables directly.
- Every MCP tool schema has a contract test.
- Every bug fix adds a regression test.
- Database migrations are additive and immutable after release.
- Prompts and evaluation datasets are versioned.
- Secrets, browser sessions, Telegram media, and user exports are never committed.

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

## 19. Execution Preflight and Build Sequence

### Build readiness check

Before writing application code, Codex or Claude Code must confirm:

1. **Repository target:** the empty local folder in which the Git repository will be created.
2. **Baseline model:** OpenAI or Anthropic, plus the initial model name. Do not request the API key in chat.
3. **Household seed data:** the private WhatsApp export path, if available. The export must be stored under `.private/` or another ignored local path.
4. **Acceptance data:** the initial query set and tuna-quinoa-salad fixture are approved, or any requested changes are recorded.
5. **Toolchain:** supported Python, `uv`, Git, Make, and any later Playwright dependencies are available.

The agent then initializes Git, creates the repository structure, writes `.gitignore` and `.env.example`, creates the local `.env`, and verifies that `.env` and `.private/` are ignored before any secret or household data is added.

Preflight commands must include equivalent checks for:

```text
git check-ignore .env
git check-ignore .private/whatsapp-export.txt
make setup
make test
make lint
make typecheck
```

Do not place secrets in the build prompt or specification. After scaffolding, the user adds credentials directly to the local `.env`. NYT authentication occurs interactively in the dedicated Playwright browser profile; the application retains the session locally rather than storing an NYT password. The Telegram bot token is added to `.env` after the user creates the bot through BotFather.

If the repository path or baseline-model choice is missing, the agent must ask one focused question and stop before generating application code. If the WhatsApp export or live credentials are unavailable, the agent may still scaffold the repository and complete the offline core using synthetic fixtures and mocked providers. It must clearly state that household categorization, live NYT ingestion, model behavior, or Telegram integration has not yet been validated, as applicable.

**Preflight gate:** Git is initialized; `.env.example` is committed; local `.env` and `.private/` are confirmed ignored; offline setup succeeds; and missing live inputs are explicitly recorded without blocking offline development.

### Stage 0 — Seed and acceptance data

- Export current WhatsApp recipe conversation.
- Extract representative recipe links.
- Approve the first query set and tuna-salad expected output.

**Gate:** fixtures and expected results exist before application generation.

### Stage 1 — One-shot core repository

Build the repository scaffolding, SQLite schema, model interface, five MCP tools, NYT fixture importer, personal-recipe importer, categorization workflow, deterministic recommendation logic, correction flow, tests, eval runner, CI, and documentation.

**Gate:** a stored fixture and tuna salad can be saved, categorized, corrected, retrieved, and recommended through an MCP client with all offline tests passing.

### Stage 2 — Live NYT ingestion and historical backfill

- Add HTTP JSON-LD fetch.
- Add authenticated Playwright fallback.
- Import and categorize the WhatsApp export.
- Review the categorization report.
- Re-run the import to confirm it is idempotent.

**Gate:** representative historical recipes are stored with approved classifications and duplicates are prevented.

### Stage 3 — Telegram text experience

- Create the bot, disable privacy mode, create the household group.
- Add user and chat allowlists and member mapping.
- Support save, query, correction, and rating messages, including reply-to and ordinal references.
- Run as a launchd daemon on the Mac mini (Section 19A).

**Gate:** Alex can save a recipe from the NYT app share sheet and Sam can retrieve it in the same group, with the service surviving a Mac mini reboot.

### Stage 4 — Photo input

- Add temporary media handling.
- Add structured image ingredient extraction.
- Confirm uncertain ingredients.
- Delete raw images after processing.

**Gate:** a fridge or pantry photo produces three recommendations based only on confirmed ingredients.

### Stage 5 — Real-use pilot

Use the assistant for approximately two weeks or 20–30 recommendation requests. Review failed searches, corrections, selected recipes, and missing categories.

**Gate:** evidence determines whether persistent pantry state, shopping lists, voice notes, a WhatsApp channel, or additional taxonomy are justified.

### Stage 6 — Multi-model experiment

Freeze the single-model baseline. Substitute one task at a time with smaller hosted or local models:

- ingredient normalization
- recipe categorization
- query interpretation
- photo recognition

Compare quality, latency, and cost using the same approved evaluation set. Do not change prompts, taxonomy, and models simultaneously.

---

## 19A. Running on the Mac mini

The Mac mini is the only runtime host. Everything below is documented in `deploy/README.md` and automated by `make install-daemon` where practical.

### Machine

- macOS with Python 3.13 installed through `uv`.
- Energy settings: never sleep, wake for network access, restart automatically after a power failure.
- Automatic login is not required; the bot runs as a LaunchDaemon, not a LaunchAgent, so it starts without a user session.
- Tailscale installed if the optional shortcut endpoint or remote MCP access is wanted. Nothing else is exposed to the network.

### Processes

- `com.recipe-mcp.telegram` LaunchDaemon runs `uv run --env-file .env recipe-mcp serve-telegram` from the repository directory with `KeepAlive` and `RunAtLoad`. Logs go to `/Library/Logs/recipe-mcp/`.
- The MCP server is not a daemon. The Telegram host spawns it over stdio, and Codex or Claude Code spawn their own instance on demand.
- Long polling means the daemon only makes outbound HTTPS requests to Telegram. No inbound port, no tunnel, no webhook secret.

### NYT session

- The dedicated Playwright profile lives at `NYT_BROWSER_PROFILE_PATH`. Login is done once by running `make nyt-login`, which opens a headed browser for a manual sign-in and closes it when the session cookie is present.
- `make doctor` checks the session and reports expiry without printing cookies.

### Operations

- `make doctor` is the first thing to run after any change or reboot.
- `make smoke` sends one test message to the group and expects a reply within 30 seconds.
- Database backups: a nightly `launchd` job copies `data/recipes.db` to `.private/backups/` using SQLite’s online backup API, keeping 14 days.
- Upgrades: `git pull`, `uv sync`, `make test`, `sudo launchctl kickstart -k system/com.recipe-mcp.telegram`.

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

- [ ] All unit, contract, and integration tests pass
- [ ] Initial synthetic eval results documented
- [ ] Live smoke-test procedure documented
- [ ] No secrets, private exports, private evals, or member IDs in Git history
- [ ] `.env.example` complete
- [ ] Local `.env` and `.private/` confirmed ignored by Git
- [ ] Configuration validation fails safely without revealing secret values
- [ ] `AGENTS.md` and `CLAUDE.md` aligned
- [ ] README supports setup on a fresh Mac
- [ ] `deploy/README.md` tested on a fresh Mac mini
- [ ] Fresh-clone user can complete the synthetic-data MCP demonstration
- [ ] Codex and Claude Code MCP configuration examples have been tested
- [ ] SECURITY.md documents Telegram, browser-session, and local-MCP risks
- [ ] Dependency and secret scans completed
- [ ] Sample data is synthetic or licensed for publication
- [ ] MIT license included
- [ ] Personal identifiers and household data absent from repository
- [ ] Repository visibility switched from private to public

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

Open ideas and agreed follow-ups that are not yet specified live in `IDEAS.md`, tagged `follow-up`, `idea`, `ops` or `deferred`. An idea is written into this spec before it is built.

- Whether to add a WhatsApp Business sender as a second channel after the pilot (requires Meta Business Portfolio, public webhook, tunnel, per-message cost, and the 24-hour reply window; no business verification needed for a reply-only bot)
- Whether remote MCP access from a laptop over Tailscale is worth the setup
- Whether additional recipe sites beyond NYT Cooking should be parsed and categorized
- Whether SQLite creates a real concurrency or operational limitation
- Whether persistent pantry state is useful enough to justify freshness and quantity management
- Whether shopping-list generation is used frequently enough to add as an MCP tool
- Whether voice-note transcription belongs in the application
- Which individual tasks merit local-model replacement after baseline evaluation
- Whether a private web reading interface is necessary beyond Telegram summaries and source links

---

*Spec version 3.5 — as 3.4 plus food types per ingredient and a main-ingredient filter; 3.4: agent-as-brain MVP (Claude Code), deterministic MCP server; otherwise as 3.3: single-model MVP on a shared Telegram group with long polling, Mac mini deployment, corrections through MCP, member identity, conversation state, idempotent WhatsApp backfill, and multi-model evaluation.*
