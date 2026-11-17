"""Pick a course from a few letters, without importing the service (stays instant).

Accepts the Moodle id (``64462``), the subject code (``G4012224``), the alias shown in
«Os meus cursos» (``ia``, ``soi``, ``asr``) or words of the name (``redes``,
``sistemas op``). Courses of the current academic year win over older ones, and an
exact title beats a title that merely contains the words.
"""

from __future__ import annotations

import re
from typing import Any

from .sources import academic_year
from .ui import course_alias, course_code, course_title, fold

_YEAR = re.compile(r"\[(\d{4}/\d{4})\]")


class CourseNotFound(LookupError):
    def __init__(self, message: str, options: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.options = options or []


def course_year(course: dict[str, Any]) -> str | None:
    for field in ("full_name", "short_name"):
        match = _YEAR.search(str(course.get(field) or ""))
        if match:
            return match.group(1)
    return None


def current(courses: list[dict[str, Any]], year: str | None = None) -> list[dict[str, Any]]:
    """This academic year's courses (or those without a year in their name)."""

    year = year or academic_year()
    return [course for course in courses if course_year(course) in {None, year}]


def _tokens(course: dict[str, Any]) -> list[str]:
    return [
        token
        for token in re.split(r"[^0-9a-z]+", fold(course_title(course.get("full_name"))))
        if token
    ]


def find(courses: list[dict[str, Any]], query: str) -> dict[str, Any]:
    text = query.strip()
    if not text:
        raise CourseNotFound("Indica una asignatura.")
    folded = fold(text)
    words = [word for word in re.split(r"[^0-9a-z]+", folded) if word]
    if text.isdigit():
        found = [course for course in courses if int(course.get("id") or 0) == int(text)]
    elif re.fullmatch(r"[gG]\d{4}[0-9A-Za-z]{3}[A-Za-z]?", text):
        found = [
            course for course in courses if course_code(course.get("full_name")) == text.upper()
        ]
    else:
        found = []
        for rule in (
            lambda c: fold(course_title(c.get("full_name"))) == folded,
            lambda c: course_alias(c.get("full_name")) == folded,
            lambda c: all(word in _tokens(c) for word in words),
            lambda c: all(any(t.startswith(word) for t in _tokens(c)) for word in words),
            lambda c: folded in fold(course_title(c.get("full_name"))),
        ):
            found = [course for course in courses if rule(course)]
            if found:
                break
    preferred = current(found) or found
    if len(preferred) == 1:
        return preferred[0]
    if not preferred:
        raise CourseNotFound(f"No encontré ninguna asignatura que coincida con «{query}».")
    raise CourseNotFound(f"«{query}» coincide con varias asignaturas:", preferred)
