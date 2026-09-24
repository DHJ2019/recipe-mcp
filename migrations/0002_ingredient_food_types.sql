-- A person's correction of an ingredient's food types in one recipe
-- ("oyster mushroom is not shellfish"). ingredients.contains_* stay the shared,
-- lexicon-derived defaults; a row here overrides them for this recipe only.
CREATE TABLE IF NOT EXISTS recipe_ingredient_food_types (
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    canonical_name TEXT NOT NULL,
    contains_meat INTEGER NOT NULL DEFAULT 0,
    contains_fish INTEGER NOT NULL DEFAULT 0,
    contains_shellfish INTEGER NOT NULL DEFAULT 0,
    contains_dairy INTEGER NOT NULL DEFAULT 0,
    contains_egg INTEGER NOT NULL DEFAULT 0,
    member_id INTEGER REFERENCES members(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (recipe_id, canonical_name)
);
