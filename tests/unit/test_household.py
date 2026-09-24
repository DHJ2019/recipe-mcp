from recipe_mcp.domain.household import is_allowed, normalize_phone, resolve_member
from recipe_mcp.domain.models import Member


def test_normalize_phone_variants() -> None:
    assert normalize_phone("whatsapp:+1 (555) 010-0100") == "+15550100100"
    assert normalize_phone("0044 20 7946 0000") == "+442079460000"
    assert normalize_phone("+44 20 7946 0000") == "+442079460000"
    assert normalize_phone("123") is None
    assert normalize_phone("") is None


def test_allowlist_check() -> None:
    allow = ["+15550100100", "+442079460000"]
    assert is_allowed("whatsapp:+15550100100", allow)
    assert not is_allowed("+15550100199", allow)
    assert not is_allowed("garbage", allow)


def test_resolve_member_respects_active_flag() -> None:
    members = [
        Member(
            id=1,
            household_id=1,
            member_key="a",
            display_name="A",
            normalized_phone_number="+15550100100",
        ),
        Member(
            id=2,
            household_id=1,
            member_key="b",
            display_name="B",
            normalized_phone_number="+15550100101",
            active=False,
        ),
    ]
    assert resolve_member("+1 555 010 0100", members) is not None
    assert resolve_member("+15550100101", members) is None
    assert resolve_member("+15550100102", members) is None
