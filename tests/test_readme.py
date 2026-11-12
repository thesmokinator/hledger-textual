"""Guards for the README gallery and local links (issue #161)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
README = REPO_ROOT / "README.md"

_RELATIVE_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)\"'#]+)(?:\"[^\"]*\")?\)")


def _relative_links() -> list[str]:
    """Return every relative link target in README.md."""
    targets = []
    for match in _RELATIVE_LINK_RE.finditer(README.read_text(encoding="utf-8")):
        target = match.group(1).strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        targets.append(target)
    return targets


class TestReadme:
    """README must keep its gallery and local links intact."""

    def test_no_orphan_screenshots(self) -> None:
        """Gallery images, if any, must be referenced from README.md.

        The screenshots gallery was removed in favour of the demo video;
        this guard fails if orphan images are reintroduced without a
        matching README reference.
        """
        shots_dir = REPO_ROOT / "docs" / "screenshots"
        shots = sorted(shots_dir.glob("*")) if shots_dir.is_dir() else []
        text = README.read_text(encoding="utf-8")
        orphans = [
            shot.relative_to(REPO_ROOT).as_posix()
            for shot in shots
            if shot.relative_to(REPO_ROOT).as_posix() not in text
        ]
        assert not orphans, f"unreferenced screenshots: {orphans}"

    def test_relative_links_resolve(self) -> None:
        """Every relative README link points at an existing file."""
        missing = [
            target
            for target in _relative_links()
            if not (REPO_ROOT / target).exists()
        ]
        assert not missing, f"broken README links: {missing}"

    def test_code_fences_balanced(self) -> None:
        """README has no unclosed fenced code block."""
        fences = [
            line
            for line in README.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("```")
        ]
        assert len(fences) % 2 == 0, "unbalanced code fences in README.md"
