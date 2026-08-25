"""The two copies of every shipped doc must not drift.

`skills/` (what GitHub / `npx skills add` serves) and
`src/claude_statusbar/skills/` (what the wheel and the binary install) are
separate files with no sync step. They had silently diverged by 12 rows and a
description line — the packaged copy documented a dozen toggles the GitHub
copy never mentioned, and nothing failed.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAIRS = [
    (ROOT / "skills", ROOT / "src" / "claude_statusbar" / "skills"),
    (ROOT / "commands", ROOT / "src" / "claude_statusbar" / "commands"),
]


def _files(root: Path):
    return {p.relative_to(root): p for p in root.rglob("*.md")} if root.is_dir() else {}


@pytest.mark.parametrize("repo_dir,packaged_dir", PAIRS,
                         ids=lambda p: p.name if hasattr(p, "name") else str(p))
def test_repo_and_packaged_copies_are_identical(repo_dir, packaged_dir):
    repo, packaged = _files(repo_dir), _files(packaged_dir)
    assert repo, f"no docs found under {repo_dir}"
    assert set(repo) == set(packaged), (
        f"file sets differ between {repo_dir} and {packaged_dir}: "
        f"only in repo={sorted(map(str, set(repo) - set(packaged)))}, "
        f"only in packaged={sorted(map(str, set(packaged) - set(repo)))}"
    )
    for rel, path in repo.items():
        assert path.read_text("utf-8") == packaged[rel].read_text("utf-8"), (
            f"{rel} differs between the repo copy and the packaged copy — "
            f"users get the packaged one; keep them in sync"
        )
