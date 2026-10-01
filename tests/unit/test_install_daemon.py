import plistlib
from pathlib import Path

from recipe_mcp.cli.main import BACKUP_PLIST, render_daemon_plist


def test_daemon_runs_as_the_invoking_user_not_root() -> None:
    rendered = render_daemon_plist(
        "someone", Path("/Users/someone"), "/opt/homebrew/bin/uv", Path("/Users/someone/repo")
    )
    plist = plistlib.loads(rendered.encode("utf-8"))
    assert plist["UserName"] == "someone"
    assert plist["EnvironmentVariables"]["HOME"] == "/Users/someone"
    assert plist["WorkingDirectory"] == "/Users/someone/repo"
    assert plist["ProgramArguments"][0] == "/opt/homebrew/bin/uv"
    assert plist["ProgramArguments"][-1] == "serve-telegram"
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert "__" not in rendered


def test_backup_job_runs_nightly_as_the_invoking_user() -> None:
    rendered = render_daemon_plist(
        "someone",
        Path("/Users/someone"),
        "/opt/homebrew/bin/uv",
        Path("/Users/someone/repo"),
        template=BACKUP_PLIST,
    )
    plist = plistlib.loads(rendered.encode("utf-8"))
    assert plist["Label"] == "com.recipe-mcp.backup"
    assert plist["UserName"] == "someone"
    assert plist["WorkingDirectory"] == "/Users/someone/repo"
    assert plist["ProgramArguments"][-1] == "backup"
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 17}
    assert "KeepAlive" not in plist and "RunAtLoad" not in plist
    assert "__" not in rendered
