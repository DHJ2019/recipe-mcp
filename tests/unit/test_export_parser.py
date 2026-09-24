from pathlib import Path

from recipe_mcp.adapters.whatsapp.export_parser import parse_export, parse_export_text


def test_parse_ios_export(export_path: Path) -> None:
    messages = parse_export(export_path)
    assert len(messages) == 8
    assert messages[0].sender == "Alex"
    assert messages[1].urls == [
        "https://cooking.nytimes.com/recipes/1000001-test-lemon-chicken-thighs?utm_source=share&smid=ck-recipe-ios-share"
    ]
    assert "continues here" in messages[6].text
    assert messages[7].text == "👍"


def test_parse_android_formats() -> None:
    text = "12/03/2024, 19:42 - Sam: hello https://example.com/x\n3/12/24, 7:42 PM - Alex: hi\n"
    messages = parse_export_text(text)
    assert [m.sender for m in messages] == ["Sam", "Alex"]
    assert messages[0].urls == ["https://example.com/x"]
    assert messages[1].timestamp == "3/12/24, 7:42 PM"
