"""One-time (and repeatable) import of recipe links from an exported WhatsApp chat.

The import is idempotent by canonical URL, so periodic re-exports can be re-run.
Unsupported links are stored as ``source_type: other`` stubs and listed separately.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from recipe_mcp.adapters.whatsapp.export_parser import parse_export
from recipe_mcp.db.repositories import MemberRepository
from recipe_mcp.domain.urls import UrlKind, canonicalize_url, classify_url
from recipe_mcp.services.ingestion import IngestionError, IngestionService


@dataclass
class ImportEntry:
    url: str
    canonical_url: str
    sender: str
    timestamp: str
    status: str
    title: str = ""
    detail: str = ""
    member_key: str | None = None


@dataclass
class ImportReport:
    entries: list[ImportEntry] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.status] = out.get(e.status, 0) + 1
        return out

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["status", "title", "canonical_url", "sender", "member", "timestamp", "detail"]
        )
        for e in self.entries:
            writer.writerow(
                [
                    e.status,
                    e.title,
                    e.canonical_url,
                    e.sender,
                    e.member_key or "",
                    e.timestamp,
                    e.detail,
                ]
            )
        return buf.getvalue()

    def to_markdown(self) -> str:
        lines = ["# WhatsApp import report", ""]
        for status, n in sorted(self.counts().items()):
            lines.append(f"- {status}: {n}")
        recipes = [
            e
            for e in self.entries
            if e.status not in {"stored_unsupported", "unsupported_duplicate"}
        ]
        others = [
            e for e in self.entries if e.status in {"stored_unsupported", "unsupported_duplicate"}
        ]
        lines += [
            "",
            "## Recipes",
            "",
            "| status | title | url | sender | detail |",
            "|---|---|---|---|---|",
        ]
        for e in recipes:
            lines.append(
                f"| {e.status} | {e.title} | {e.canonical_url} | {e.sender} | {e.detail} |"
            )
        if others:
            lines += [
                "",
                "## Other links (stored, not categorized)",
                "",
                "| status | title | url | sender |",
                "|---|---|---|---|",
            ]
            for e in others:
                lines.append(f"| {e.status} | {e.title} | {e.canonical_url} | {e.sender} |")
        return "\n".join(lines) + "\n"


class WhatsAppImportService:
    def __init__(
        self, ingestion: IngestionService, members: MemberRepository, household_id: int
    ) -> None:
        self.ingestion = ingestion
        self.members = members
        self.household_id = household_id

    def plan(self, export_path: Path) -> list[ImportEntry]:
        """Extract, canonicalize and deduplicate links without touching the network."""
        seen: set[str] = set()
        planned: list[ImportEntry] = []
        for message in parse_export(export_path):
            for url in message.urls:
                canonical = canonicalize_url(url)
                if canonical in seen:
                    continue
                seen.add(canonical)
                kind = classify_url(url)
                if kind == UrlKind.INVALID:
                    continue
                supported = kind in {UrlKind.NYT_RECIPE, UrlKind.NYT_SHORTLINK}
                member = self.members.by_export_name(self.household_id, message.sender)
                planned.append(
                    ImportEntry(
                        url=url,
                        canonical_url=canonical,
                        sender=message.sender,
                        timestamp=message.timestamp,
                        status="planned" if supported else "planned_unsupported",
                        member_key=member.member_key if member else None,
                    )
                )
        return planned

    def run(self, export_path: Path) -> ImportReport:
        report = ImportReport()
        for entry in self.plan(export_path):
            member = (
                self.members.by_key(self.household_id, entry.member_key)
                if entry.member_key
                else None
            )
            member_id = member.id if member else None
            try:
                result = self.ingestion.save_url(entry.url, member_id=member_id)
            except IngestionError as exc:
                entry.status = "failed"
                entry.detail = str(exc)
            else:
                entry.title = result.recipe.title
                if not result.recipe.is_recommendable:
                    entry.status = (
                        "stored_unsupported" if result.created else "unsupported_duplicate"
                    )
                else:
                    entry.status = "imported" if result.created else "duplicate"
                    if result.needs_review:
                        entry.detail = "needs review"
            report.entries.append(entry)
        return report
