"""Contract tests for structured model outputs and the fake provider."""

from __future__ import annotations

from recipe_mcp.providers.base import (
    PersonalRecipeDraft,
    QueryConstraints,
    RecipeClassification,
    RecipeClassificationInput,
)
from recipe_mcp.providers.fake import FakeModelClient


def test_schemas_are_closed_objects_for_strict_structured_output() -> None:
    for schema in (RecipeClassification, PersonalRecipeDraft, QueryConstraints):
        js = schema.model_json_schema()
        assert js["type"] == "object"
        assert set(js["properties"])  # non-empty


def test_fake_classification_validates_and_respects_taxonomy() -> None:
    response = FakeModelClient().classify_recipe(
        RecipeClassificationInput(
            title="Thai Pumpkin Soup",
            ingredients=["pumpkin", "coconut milk", "red curry paste", "vegetable stock"],
            total_minutes=40,
        )
    )
    out = RecipeClassification.model_validate(response.output.model_dump())
    assert out.cuisine == "thai"
    assert out.dish_type == "soup"
    assert "vegan" in out.dietary_suitability
    assert "cozy" in out.character
    assert out.effort == "weeknight"
    assert 0 <= out.confidence <= 1
    assert response.prompt_version == "v2"


def test_fake_draft_does_not_invent_details() -> None:
    draft = (
        FakeModelClient()
        .parse_personal_recipe(
            "Tuna salad with tomato, quinoa, cucumber, arugula and seeds. Need to season the tuna."
        )
        .output
    )
    assert draft.total_minutes is None
    assert draft.servings is None
    assert set(draft.ingredients) == {"tuna", "tomato", "quinoa", "cucumber", "arugula", "seeds"}
    assert draft.notes == ["Need to season the tuna"]
    assert "tuna" in draft.title.lower() and "salad" in draft.title.lower()


def test_fake_query_interpretation() -> None:
    fake = FakeModelClient()
    q = fake.interpret_query("Something cozy under 45 minutes.").output
    assert q.character == ["cozy"] and q.max_minutes == 45
    q = fake.interpret_query("Vegetarian Thai food").output
    assert q.dietary == ["vegetarian"] and q.cuisine == "thai"
    q = fake.interpret_query("We have salmon, cabbage and carrots. What can we make?").output
    assert q.available_ingredients == ["salmon", "cabbage", "carrots"]
    q = fake.interpret_query("Something light that we both like").output
    assert q.for_household and q.character == ["light"]
    q = fake.interpret_query("A soup using cabbage").output
    assert q.dish_type == "soup" and q.available_ingredients == ["cabbage"]
