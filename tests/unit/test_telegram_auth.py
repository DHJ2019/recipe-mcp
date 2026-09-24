from recipe_mcp.adapters.telegram.auth import authorize
from recipe_mcp.settings import load_settings

SETTINGS = load_settings(
    env_file=None, telegram_allowed_user_ids="111,222", telegram_group_chat_id=-100999
)


def test_group_and_private_chats_for_allowlisted_users() -> None:
    assert authorize(111, -100999, SETTINGS).allowed
    assert authorize(222, 222, SETTINGS).allowed  # private chat with the bot
    assert not authorize(111, 222, SETTINGS).allowed  # someone else's private chat
    assert not authorize(333, -100999, SETTINGS).allowed  # stranger in the group
    assert not authorize(111, -100123, SETTINGS).allowed  # allowed user, other group
    assert not authorize(None, -100999, SETTINGS).allowed
    assert authorize(333, -100999, SETTINGS).reason == "user not allowlisted"
