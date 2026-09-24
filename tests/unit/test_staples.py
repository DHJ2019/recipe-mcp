from pathlib import Path

from recipe_mcp.domain import staples
from recipe_mcp.domain.ingredients import normalize_ingredient


def test_default_staples_loaded_from_yaml() -> None:
    assert "olive oil" in staples.staples()
    assert normalize_ingredient("2 tablespoons olive oil").is_staple
    assert not normalize_ingredient("salmon").is_staple


def test_reload_from_custom_file(tmp_path: Path) -> None:
    custom = tmp_path / "staples.yaml"
    custom.write_text("staples:\n  - salmon\n")
    try:
        assert staples.reload(custom) == frozenset({"salmon"})
        assert normalize_ingredient("salmon").is_staple
        assert not normalize_ingredient("olive oil").is_staple
    finally:
        staples.reload()
    assert normalize_ingredient("olive oil").is_staple
