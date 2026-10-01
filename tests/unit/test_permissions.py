from pathlib import Path

from recipe_mcp.cli.main import exposed_to_others


def test_a_readable_file_in_an_open_folder_is_exposed(tmp_path: Path) -> None:
    folder = tmp_path / "open"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    secret = folder / ".env"
    secret.write_text("TOKEN=x")
    secret.chmod(0o644)
    tmp_path.chmod(0o755)
    assert exposed_to_others(secret, root=tmp_path)
    secret.chmod(0o600)
    assert not exposed_to_others(secret, root=tmp_path)


def test_a_private_folder_protects_everything_inside_it(tmp_path: Path) -> None:
    private = tmp_path / ".private"
    private.mkdir()
    private.chmod(0o700)
    inside = private / "members.yaml"
    inside.write_text("alex: {}")
    inside.chmod(0o644)
    assert not exposed_to_others(inside, root=tmp_path)
    assert not exposed_to_others(private, root=tmp_path)


def test_missing_paths_are_not_reported(tmp_path: Path) -> None:
    assert not exposed_to_others(tmp_path / "nope")
