"""Text written by other people (notifications, activity names…) made safe to print.

* :func:`scrub` removes control characters, so nothing stored from the Campus can move
  the cursor, change colours or retitle the terminal (escape-sequence injection);
* :func:`html_to_text` turns Moodle's HTML messages into readable paragraphs with the
  standard library alone.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

# C0 controls except tab and newline, DEL and the C1 range (includes CSI, OSC, ESC).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BLOCKS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_SKIP = frozenset({"script", "style", "head", "title"})


def scrub(value: Any) -> Any:
    """``value`` with every string stripped of control characters (dicts and lists too)."""

    if isinstance(value, str):
        return _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    return value


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skipping += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in _BLOCKS and tag != "li":  # list items stay together
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_to_text(html: Any, limit: int = 8_000) -> str:
    """Paragraphs separated by one blank line, spaces collapsed, at most ``limit`` chars."""

    source = str(html or "")
    if "<" in source:
        parser = _Text()
        parser.feed(source)
        parser.close()
        source = "".join(parser.parts)
    else:
        source = unescape(source)
    lines = [" ".join(line.split()) for line in scrub(source).split("\n")]
    paragraphs: list[str] = []
    for line in lines:
        if line:
            paragraphs.append(line)
        elif paragraphs and paragraphs[-1]:
            paragraphs.append("")
    text = "\n".join(paragraphs).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
