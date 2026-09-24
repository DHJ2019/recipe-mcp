-- 0001_initial: core household recipe schema (SPEC v3.3). Additive and immutable
-- after release.

CREATE TABLE IF NOT EXISTS households (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    member_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    telegram_user_id INTEGER UNIQUE,
    whatsapp_export_name TEXT,
    normalized_phone_number TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (household_id, member_key)
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    source_type TEXT NOT NULL CHECK (source_type IN ('nyt', 'personal', 'other')),
    canonical_source_url TEXT,
    title TEXT NOT NULL,
    servings TEXT,
    total_minutes INTEGER,
    notes TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('draft', 'complete')),
    content_hash TEXT NOT NULL,
    added_by_member_id INTEGER REFERENCES members(id),
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_recipes_household_url
    ON recipes(household_id, canonical_source_url) WHERE canonical_source_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_recipes_household_hash ON recipes(household_id, content_hash);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'other',
    is_staple INTEGER NOT NULL DEFAULT 0,
    contains_meat INTEGER NOT NULL DEFAULT 0,
    contains_fish INTEGER NOT NULL DEFAULT 0,
    contains_shellfish INTEGER NOT NULL DEFAULT 0,
    contains_dairy INTEGER NOT NULL DEFAULT 0,
    contains_egg INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
    position INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    quantity TEXT,
    preparation TEXT,
    PRIMARY KEY (recipe_id, ingredient_id)
);

CREATE TABLE IF NOT EXISTS recipe_facets (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    facet TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('parsed', 'rule', 'model', 'user')),
    confidence REAL NOT NULL DEFAULT 1.0,
    model_version TEXT,
    prompt_version TEXT,
    user_confirmed INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    proposed_value TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (recipe_id, facet, value)
);
CREATE INDEX IF NOT EXISTS idx_recipe_facets_facet_value ON recipe_facets(facet, value);

CREATE TABLE IF NOT EXISTS recipe_feedback (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    reported_by_member_id INTEGER REFERENCES members(id),
    sentiment TEXT NOT NULL CHECK (sentiment IN ('love', 'like', 'dislike')),
    notes TEXT,
    cooked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipe_feedback_recipe ON recipe_feedback(recipe_id);

CREATE TABLE IF NOT EXISTS model_runs (
    id INTEGER PRIMARY KEY,
    task TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    validation_status TEXT NOT NULL DEFAULT 'ok',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_runs_cache
    ON model_runs(task, input_hash, prompt_version, model);

CREATE TABLE IF NOT EXISTS model_cache (
    task TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task, input_hash, prompt_version, model)
);

-- Short-lived per-chat conversation state; the only place such state lives.
CREATE TABLE IF NOT EXISTS pending_interactions (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN (
        'recent_results', 'photo_confirmation', 'draft_confirmation', 'turn_history'
    )),
    payload TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (chat_id, kind)
);
