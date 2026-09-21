"""Fail when a relative Markdown link in the tracked docs points nowhere.

Only relative links are checked; external URLs are deliberately skipped (CI has
no business depending on the uptime of third-party sites).

Run: python scripts/check_docs_links.py    (exit 0 = every relative link resolves)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Entry points plus every Markdown file under docs/.
TARGETS = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
# Inline code spans are documentation *about* link syntax, not links.
CODE_SPAN = re.compile(r"`[^`]*`")
SKIP_PREFIXES = ("http://", "https://", "#", "mailto:")


def main() -> int:
    """Print every relative link that does not resolve; exit 1 when any fail."""
    checked = 0
    broken: list[str] = []

    for doc in TARGETS:
        if not doc.exists():
            broken.append(f"{doc.relative_to(ROOT)} (missing file)")
            continue
        text = CODE_SPAN.sub("", doc.read_text(encoding="utf-8"))
        for raw in LINK.findall(text):
            link = raw.strip()
            if link.startswith(SKIP_PREFIXES):
                continue
            target = link.split("#", 1)[0].strip()
            if not target:
                continue
            checked += 1
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {link}")

    print(f"Checked {checked} relative link(s) in {len(TARGETS)} file(s).")
    for item in broken:
        print(f"[BROKEN] {item}")
    if broken:
        print(f"FAILED: {len(broken)} broken relative link(s).")
        return 1
    print("All relative links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())