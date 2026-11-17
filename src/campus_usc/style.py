"""Zero-dependency terminal styling in the Campus Virtual's own colours.

The palette is read from the USC Moodle theme (``theme/styles.php/boost``): navy
``#000066`` as primary, mint ``#e1f4f1`` as secondary, and Bootstrap's danger, success
and warning as the Campus overrides them. Activity icons use Moodle 4's purpose colours.

Nothing here imports more than the standard library: rendering from the local cache
must start in a few milliseconds.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata

# Campus Virtual theme (cv.usc.es, theme boost, read 2026-11-17).
NAVY = "#000066"
MINT = "#e1f4f1"
RED = "#ca3120"
GREEN = "#357a32"
AMBER = "#f0ad4e"
ORANGE = "#ff7518"
GRAY = "#6a737b"
WHITE = "#ffffff"
# The navy is unreadable as text on a dark terminal: links and accents use a brighter
# blue of the same hue, legible on both light and dark backgrounds.
BLUE = "#4b5bff"
SOFT_GREEN = "#4caf50"

# Moodle 4 activity purposes (icon background colours).
PURPOSE = {
    "assessment": "#f90086",
    "collaboration": "#5b40ff",
    "communication": "#eb6200",
    "content": "#0099ad",
    "administration": "#da58ef",
    "interface": "#8d3d1b",
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\]8;[^\x1b]*\x1b\\")


class _Caps:
    """What this terminal can do; decided once, lazily."""

    def __init__(self) -> None:
        self._color: bool | None = None
        self._truecolor: bool | None = None
        self._links: bool | None = None

    def reset(self, *, color: bool | None = None) -> None:
        self._color = color
        self._truecolor = None
        self._links = None

    @property
    def color(self) -> bool:
        if self._color is None:
            if os.environ.get("NO_COLOR"):
                self._color = False
            elif os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
                self._color = True
            else:
                self._color = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
            if self._color and os.name == "nt":
                _enable_windows_vt()
        return self._color

    @property
    def truecolor(self) -> bool:
        if self._truecolor is None:
            env = os.environ
            self._truecolor = (
                env.get("COLORTERM", "").lower() in {"truecolor", "24bit"}
                or env.get("TERM_PROGRAM")
                in {"iTerm.app", "WezTerm", "vscode", "ghostty", "Hyper", "Tabby", "rio"}
                or any(name in env.get("TERM", "") for name in ("kitty", "alacritty", "foot"))
                or "WT_SESSION" in env
            )
        return self._truecolor

    @property
    def links(self) -> bool:
        if self._links is None:
            env = os.environ
            self._links = self.color and (
                env.get("TERM_PROGRAM") in {"iTerm.app", "WezTerm", "vscode", "ghostty", "rio"}
                or "kitty" in env.get("TERM", "")
                or "WT_SESSION" in env
                or "VTE_VERSION" in env
            )
        return self._links


caps = _Caps()


def _enable_windows_vt() -> None:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # noqa: BLE001 - colours are cosmetic
        pass


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _to_256(red: int, green: int, blue: int) -> int:
    if red == green == blue:
        if red < 8:
            return 16
        if red > 248:
            return 231
        return 232 + round((red - 8) / 247 * 24)
    return 16 + 36 * round(red / 255 * 5) + 6 * round(green / 255 * 5) + round(blue / 255 * 5)


def _color(value: str, background: bool) -> str:
    red, green, blue = _rgb(value)
    if caps.truecolor:
        return f"{48 if background else 38};2;{red};{green};{blue}"
    return f"{48 if background else 38};5;{_to_256(red, green, blue)}"


def paint(
    text: str,
    fg: str | None = None,
    bg: str | None = None,
    *,
    bold: bool = False,
    dim: bool = False,
    italic: bool = False,
    underline: bool = False,
) -> str:
    """``text`` with the given style, or unchanged when colours are off."""

    if not text or not caps.color:
        return text
    codes = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if italic:
        codes.append("3")
    if underline:
        codes.append("4")
    if fg:
        codes.append(_color(fg, False))
    if bg:
        codes.append(_color(bg, True))
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"


def bold(text: str) -> str:
    return paint(text, bold=True)


def muted(text: str) -> str:
    return paint(text, GRAY)


def link(text: str, url: str | None) -> str:
    """An OSC 8 hyperlink where the terminal supports it (Cmd/Ctrl+click opens it)."""

    if not url or not caps.links:
        return text
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def strip(text: str) -> str:
    return _ANSI.sub("", text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def width(text: str) -> int:
    """Visible width in terminal cells, ignoring escape sequences."""

    plain = strip(text)
    if plain.isascii():
        return len(plain)
    return sum(_char_width(char) for char in plain)


def truncate(text: str, cells: int, ellipsis: str = "…") -> str:
    """Plain ``text`` cut to ``cells`` columns. Style it after truncating."""

    if cells <= 0:
        return ""
    if width(text) <= cells:
        return text
    out, used = [], 0
    limit = cells - width(ellipsis)
    for char in text:
        size = _char_width(char)
        if used + size > limit:
            break
        out.append(char)
        used += size
    return "".join(out).rstrip() + ellipsis


_PIECES = re.compile(r"(\x1b\[[0-9;]*m|\x1b\]8;[^\x1b]*\x1b\\)")
_LINK_END = "\x1b]8;;\x1b\\"


def clip(text: str, cells: int, ellipsis: str = "…") -> str:
    """A styled ``text`` cut to ``cells`` columns, keeping its colours and links whole."""

    if width(text) <= cells:
        return text
    out: list[str] = []
    used, limit, link_open = 0, max(0, cells - width(ellipsis)), False
    for piece in _PIECES.split(text):
        if not piece:
            continue
        if _PIECES.fullmatch(piece):
            out.append(piece)
            if piece.startswith("\x1b]8;"):
                link_open = piece != _LINK_END
            continue
        for char in piece:
            size = _char_width(char)
            if used + size > limit:
                out.append(ellipsis)
                if link_open:
                    out.append(_LINK_END)
                if "\x1b[" in text:
                    out.append("\x1b[0m")
                return "".join(out)
            out.append(char)
            used += size
    return "".join(out)


def pad(text: str, cells: int, align: str = "<") -> str:
    """Pad a (possibly styled) string to ``cells`` columns."""

    gap = max(0, cells - width(text))
    if align == ">":
        return " " * gap + text
    if align == "^":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def term_width(maximum: int = 110) -> int:
    """Usable layout width: the terminal's, capped so lines stay readable."""

    columns = shutil.get_terminal_size((100, 24)).columns
    return max(40, min(columns, maximum))
