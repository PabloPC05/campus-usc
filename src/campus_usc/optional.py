"""Timetable and exam dates are optional: they come from usc.gal, not from the Campus.

The Campus is what `campus` is about. The class timetable and the official exam dates are
public pages of usc.gal, and the first time they are looked up for you takes a minute or
two (finding your subjects in the study plans). So nobody pays for them until they ask:

* they join the Taboleiro, `campus actualizar` and the background refresh only after you
  run ``campus horario`` or ``campus examenes`` once (that is the switch, nothing to set);
* ``campus horario --ocultar`` / ``campus examenes --ocultar`` take them out again.
"""

from __future__ import annotations

from . import config

FEATURES = ("horario", "examenes")
_KEY = "opcional_{}"


def enabled(feature: str) -> bool:
    return bool(config.get(_KEY.format(feature), False))


def enable(feature: str) -> bool:
    """Turns it on; True when it was off (the first time you ask for it)."""

    if enabled(feature):
        return False
    config.set_value(_KEY.format(feature), True)
    return True


def disable(feature: str) -> None:
    config.set_value(_KEY.format(feature), None)


__all__ = ["FEATURES", "disable", "enable", "enabled"]
