# The release workflow trusts scripts/release_meta.py to decide what gets
# tagged, what the notes say, and whether the version is consistent across the
# files that carry it. A wrong answer there is a public tag and an immutable
# PyPI upload, so the parsing is pinned here.
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import release_meta  # noqa: E402


CHANGELOG = """# Changelog

Intro prose that mentions v9.9.9 and must not be mistaken for a section.

---

## v3.43.2 — 2026-09-16

**Two profiles no longer share one usage bucket.**

- The config dir now comes from the session's transcript path.

---

## v3.43.1 — 2026-09-13

**The ocs address gets its own line.**

- Older entry.
"""


def test_version_comes_from_the_project_table():
    # A `version = ` under a [tool.*] table must not win over the project's.
    text = '[project]\nname = "x"\nversion = "3.43.2"\n\n[tool.z]\nversion = "0.1"\n'
    assert release_meta.pyproject_version(text) == "3.43.2"


def test_notes_stop_at_the_next_entry():
    notes = release_meta.changelog_section("3.43.2", CHANGELOG)
    assert "share one usage bucket" in notes
    assert "ocs address" not in notes
    # the `---` rule between entries belongs to neither section
    assert not notes.rstrip().endswith("-")


def test_title_uses_the_bold_headline():
    title = release_meta.title("3.43.2", release_meta.changelog_section("3.43.2", CHANGELOG))
    assert title == "v3.43.2 — Two profiles no longer share one usage bucket"


def test_title_falls_back_to_the_bare_tag():
    assert release_meta.title("1.2.3", "- just a bullet") == "v1.2.3"


def test_missing_section_is_an_error_not_an_empty_release():
    with pytest.raises(SystemExit):
        release_meta.changelog_section("9.9.9", CHANGELOG)


def _manifest(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def test_drift_reports_each_disagreeing_manifest(tmp_path):
    plugin = _manifest(tmp_path, "plugin.json", {"version": "3.43.2"})
    market = _manifest(tmp_path, "marketplace.json",
                       {"metadata": {"version": "3.43.1"}})
    drift = release_meta.version_drift("3.43.2", (plugin, market))
    assert len(drift) == 1 and "marketplace.json" in drift[0]
    assert release_meta.version_drift("3.43.2", (plugin,)) == []


def test_the_repo_itself_is_consistent():
    """Guards the real files: a bump that misses a manifest fails here rather
    than mid-release."""
    version = release_meta.pyproject_version()
    assert release_meta.version_drift(version) == []
    assert release_meta.changelog_section(version)
