"""Parse a WhatsApp "Export chat" text file into messages (no network, no model).

Supported line shapes (iOS and Android exports):

    [12/03/2024, 19:42:11] Alex: text
    12/03/2024, 19:42 - Alex: text
    3/12/24, 7:42 PM - Alex: text

Continuation lines without a timestamp are appended to the previous message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from recipe_mcp.domain.urls import extract_urls

_LINE_RE = re.compile(
    r"^‎?\[?(?P<ts>\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?"
    r"\s*(?:-\s*)?(?P<sender>[^:]{1,60}?):\s(?P<text>.*)$"
)


@dataclass
class ExportMessage:
    timestamp: str
    sender: str
    text: str
    urls: list[str] = field(default_factory=list)


def parse_export_text(content: str) -> list[ExportMessage]:
    messages: list[ExportMessage] = []
    for raw_line in content.splitlines():
        line = raw_line.rstrip("\n").lstrip("﻿")
        match = _LINE_RE.match(line)
        if match:
            messages.append(
                ExportMessage(
                    timestamp=match.group("ts").strip(),
                    sender=match.group("sender").strip(),
                    text=match.group("text").strip(),
                )
            )
        elif messages and line.strip():
            messages[-1].text += "\n" + line.strip()
    for message in messages:
        message.urls = extract_urls(message.text)
    return messages


def parse_export(path: Path) -> list[ExportMessage]:
    return parse_export_text(path.read_text(encoding="utf-8", errors="replace"))
