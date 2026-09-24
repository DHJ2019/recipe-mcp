"""Household members from the private ``members.yaml`` (never committed).

Format::

    members:
      - key: alex
        display_name: Alex
        telegram_user_id: 123456789
        whatsapp_export_name: Alex
"""

from __future__ import annotations

from pathlib import Path

import yaml

from recipe_mcp.db.repositories import MemberRepository
from recipe_mcp.domain.models import Member


def load_members_file(path: Path, household_id: int) -> list[Member]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("members", []) if isinstance(data, dict) else data
    members: list[Member] = []
    for entry in entries or []:
        key = str(entry.get("key") or entry.get("member_key") or "").strip().lower()
        if not key:
            continue
        telegram_id = entry.get("telegram_user_id")
        members.append(
            Member(
                household_id=household_id,
                member_key=key,
                display_name=str(entry.get("display_name") or key.capitalize()),
                telegram_user_id=int(telegram_id) if telegram_id is not None else None,
                whatsapp_export_name=entry.get("whatsapp_export_name"),
                role=str(entry.get("role", "member")),
                active=bool(entry.get("active", True)),
            )
        )
    return members


def sync_members(repo: MemberRepository, path: Path, household_id: int) -> list[Member]:
    """Upsert every member declared in the file. Returns the synced members."""
    return [repo.upsert(m) for m in load_members_file(path, household_id)]
