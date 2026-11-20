"""Compatibility helpers for the Textual versions we support.

hledger-textual targets Textual 8.x, where ``Select`` exposes the "nothing
selected" sentinel as ``Select.NULL``.  Older releases only expose
``Select.BLANK``, and a future release could rename it again, so the code must
not depend on the attribute name.

Both sentinels are instances of :class:`textual.widgets.select.NoSelection`,
which is stable across versions: comparing on the type keeps every call site
working without version checks.
"""

from __future__ import annotations

from textual.widgets.select import NoSelection

#: Lowest Textual version supported, mirroring the constraint in pyproject.toml.
MIN_TEXTUAL_VERSION: tuple[int, int] = (8, 0)

#: Highest Textual major version supported (exclusive).
MAX_TEXTUAL_MAJOR: int = 9


def is_no_selection(value: object) -> bool:
    """Return whether a ``Select`` value means "no selection".

    ``Select.NULL`` (Textual 8) and ``Select.BLANK`` (Textual 7) are both
    instances of :class:`~textual.widgets.select.NoSelection`, so an
    ``isinstance`` check is portable across versions and survives a rename of
    the class attribute.

    Args:
        value: A value read from ``Select.value`` or ``Select.Changed.value``.

    Returns:
        ``True`` when *value* is the "no selection" sentinel.
    """
    return isinstance(value, NoSelection)


def parse_textual_version(version: str) -> tuple[int, ...]:
    """Parse a Textual version string into a comparable tuple.

    Only the leading numeric components are kept, so pre-release suffixes
    (``"8.3.0b1"``) and local versions (``"8.2.8+local"``) are tolerated.

    Args:
        version: Version string such as ``"8.2.8"``.

    Returns:
        A tuple of integers, e.g. ``(8, 2, 8)``.  Unparsable input yields ``()``.
    """
    parts: list[int] = []
    for chunk in version.split("."):
        leading = ""
        for character in chunk:
            if not character.isdigit():
                break
            leading += character
        if not leading:
            break
        parts.append(int(leading))
        if leading != chunk:
            break
    return tuple(parts)


def is_supported_textual(version: str) -> bool:
    """Return whether *version* is inside the supported Textual range.

    Args:
        version: Installed Textual version string.

    Returns:
        ``True`` for versions ``>= 8.0`` and ``< 9``.
    """
    parsed = parse_textual_version(version)
    if not parsed:
        return False
    major, minor = (parsed + (0, 0))[:2]
    return (major, minor) >= MIN_TEXTUAL_VERSION and major < MAX_TEXTUAL_MAJOR
