"""Persistent pet identity tests."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_statusbar import pet_state


# ---------------------------------------------------------------------------
# load / save round-trip + corruption tolerance
# ---------------------------------------------------------------------------
def test_load_returns_empty_when_missing(tmp_path):
    state = pet_state.load_state(tmp_path / "missing.json")
    assert state == pet_state.PersistentPet()
    assert state.has_identity is False


def test_load_returns_empty_on_corrupt_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert pet_state.load_state(p) == pet_state.PersistentPet()


def test_load_returns_empty_on_non_dict_json(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[]", encoding="utf-8")
    assert pet_state.load_state(p) == pet_state.PersistentPet()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "pet.json"
    s = pet_state.PersistentPet(name="Tofu", first_seen="2026-01-15T00:00:00+00:00",
                                 last_session_id="abc", total_sessions=5)
    assert pet_state.save_state(s, p) is True
    assert pet_state.load_state(p) == s


def test_save_is_atomic(tmp_path):
    """Two writes must not leave a .tmp file behind (regression — uses
    cache.atomic_write_text under the hood)."""
    p = tmp_path / "pet.json"
    pet_state.save_state(pet_state.PersistentPet(name="A"), p)
    pet_state.save_state(pet_state.PersistentPet(name="B"), p)
    leftover = list(tmp_path.glob(".pet.json.*.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# ensure_identity
# ---------------------------------------------------------------------------
def test_ensure_identity_assigns_on_first_call():
    state, changed = pet_state.ensure_identity(pet_state.PersistentPet(),
                                                session_id="some-session")
    assert changed is True
    assert state.name in pet_state._NAMES
    assert state.first_seen != ""


def test_ensure_identity_is_no_op_when_already_set():
    pre = pet_state.PersistentPet(name="Tofu",
                                    first_seen="2026-01-01T00:00:00+00:00")
    state, changed = pet_state.ensure_identity(pre, session_id="anything")
    assert changed is False
    assert state == pre


def test_ensure_identity_custom_name_overrides():
    state, changed = pet_state.ensure_identity(pet_state.PersistentPet(),
                                                custom_name="Whiskers")
    assert changed is True
    assert state.name == "Whiskers"


def test_ensure_identity_deterministic_from_session_id():
    """First-time-pick must be the same across two installs that started
    from the same session_id (so v2.9.4 migration doesn't surprise users)."""
    a, _ = pet_state.ensure_identity(pet_state.PersistentPet(), session_id="sid-X")
    b, _ = pet_state.ensure_identity(pet_state.PersistentPet(), session_id="sid-X")
    assert a.name == b.name


# ---------------------------------------------------------------------------
# record_session
# ---------------------------------------------------------------------------
def test_record_session_bumps_count_on_new_id():
    s = pet_state.PersistentPet(name="X", last_session_id="old", total_sessions=3)
    s2, changed = pet_state.record_session(s, "new")
    assert changed
    assert s2.total_sessions == 4
    assert s2.last_session_id == "new"


def test_record_session_no_change_for_same_id():
    s = pet_state.PersistentPet(name="X", last_session_id="same", total_sessions=3)
    s2, changed = pet_state.record_session(s, "same")
    assert not changed
    assert s2 == s


def test_record_session_ignores_empty_id():
    s = pet_state.PersistentPet(name="X", last_session_id="", total_sessions=3)
    s2, changed = pet_state.record_session(s, "")
    assert not changed


# ---------------------------------------------------------------------------
# bond_age_days
# ---------------------------------------------------------------------------
def test_bond_age_zero_for_empty_state():
    assert pet_state.bond_age_days(pet_state.PersistentPet()) == 0


def test_bond_age_naive_iso_treated_as_utc():
    """ISO without tz must not crash."""
    s = pet_state.PersistentPet(first_seen="2026-01-01T00:00:00")
    now = datetime(2026, 1, 11, tzinfo=timezone.utc)
    assert pet_state.bond_age_days(s, now) == 10


def test_bond_age_handles_tz_aware():
    s = pet_state.PersistentPet(first_seen="2026-01-01T00:00:00+00:00")
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert pet_state.bond_age_days(s, now) == 31


# ---------------------------------------------------------------------------
# bond_marker tier ladder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("days,expected", [
    (0,  ""), (6,  ""), (7, "♡"), (29, "♡"),
    (30, "♡♡"), (99, "♡♡"),
    (100, "♡♡♡"), (1000, "♡♡♡"),
])
def test_bond_marker(days, expected):
    assert pet_state.bond_marker(days) == expected


# ---------------------------------------------------------------------------
# milestone_emoji
# ---------------------------------------------------------------------------
def test_milestone_birthday():
    s = pet_state.PersistentPet(name="X", first_seen="2025-04-27T00:00:00+00:00")
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    assert pet_state.milestone_emoji(s, now) == "🎂"


def test_milestone_not_birthday_under_a_year():
    s = pet_state.PersistentPet(name="X", first_seen="2026-04-27T00:00:00+00:00")
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)  # same day, but only 0 years
    assert pet_state.milestone_emoji(s, now) == ""


@pytest.mark.parametrize("count,expected", [
    (99, ""), (100, "✨"), (101, ""),
    (500, "✨"), (1000, "✨"), (1001, ""),
])
def test_milestone_session_count(count, expected):
    s = pet_state.PersistentPet(name="X", total_sessions=count)
    assert pet_state.milestone_emoji(s) == expected


# ---------------------------------------------------------------------------
# Integration: pet.format_pet picks up identity + bond marker
# ---------------------------------------------------------------------------
def test_format_pet_uses_persistent_name(monkeypatch, tmp_path):
    """A pre-existing pet.json with name='Whiskers' must override
    the session_id-derived default."""
    p = tmp_path / "pet.json"
    pet_state.save_state(
        pet_state.PersistentPet(name="Whiskers",
                                  first_seen="2026-01-01T00:00:00+00:00",
                                  total_sessions=10),
        p,
    )
    monkeypatch.setattr(pet_state, "STATE_PATH", p)

    from claude_statusbar.pet import format_pet
    out = format_pet(50, 12, session_id="any-new-session")
    assert "Whiskers" in out


def test_format_pet_appends_bond_marker(monkeypatch, tmp_path):
    """40 days old → ♡♡."""
    p = tmp_path / "pet.json"
    long_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    pet_state.save_state(
        pet_state.PersistentPet(name="Tofu", first_seen=long_ago,
                                  total_sessions=10),
        p,
    )
    monkeypatch.setattr(pet_state, "STATE_PATH", p)

    from claude_statusbar.pet import format_pet
    out = format_pet(50, 12, session_id="x")
    assert "Tofu ♡♡" in out
