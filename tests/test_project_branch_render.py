from claude_statusbar.identity import IdentityInfo
from claude_statusbar.styles import render_identity_line
from claude_statusbar.themes import get_theme


THEME = get_theme("graphite")


def test_with_branch_and_clean():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "proj" in s
    assert "main" in s
    assert "●" not in s  # ●
    assert "⤷" in s  # ⤷
    assert "⎇" in s  # ⎇


def test_with_branch_and_dirty():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=True, use_color=False,
    )
    assert "●" in s


def test_no_git_shows_no_git_tag():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=False, branch=None,
                     detached=False, worktree_name=None, toplevel=None),
        theme=THEME, dirty=None, use_color=False,
    )
    assert "(no git)" in s
    assert "⎇" not in s


def test_detached_head_uses_short_sha():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="abc1234",
                     detached=True, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "abc1234" in s


def test_worktree_suffix_collapses_when_name_repeats_branch():
    # The worktree name adds nothing when it equals the branch already shown.
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="feat-x",
                     detached=False, worktree_name="feat-x", toplevel="/x",
                     is_worktree=True),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "🌲 worktree" in s


def test_worktree_shows_the_repo_total():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name="wt-party", toplevel="/x",
                     is_worktree=True, worktree_count=3),
        theme=THEME, dirty=False, use_color=False,
    )
    assert s.startswith("🌲 wt-party (3) ⤷ proj")


def test_worktree_total_omitted_when_unknown():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name="wt-party", toplevel="/x",
                     is_worktree=True, worktree_count=0),
        theme=THEME, dirty=False, use_color=False,
    )
    assert s.startswith("🌲 wt-party ⤷ proj")


def test_worktree_shows_its_own_name():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name="release-1.2.0-work",
                     toplevel="/x", is_worktree=True),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "proj" in s and "main" in s
    assert "🌲 release-1.2.0-work" in s
    # Leads the line — read before the repo, never scanned past.
    assert s.startswith("🌲 release-1.2.0-work ⤷ proj")


def test_worktree_name_drops_redundant_repo_prefix():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name="proj-wt-party",
                     toplevel="/x", is_worktree=True),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "🌲 wt-party" in s


def test_worktree_marker_uses_the_theme_worktree_hue():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name="wt-party", toplevel="/x",
                     is_worktree=True),
        theme=THEME, dirty=False, use_color=True,
    )
    r, g, b = THEME.wt
    assert s.startswith(f"\033[38;2;{r};{g};{b}m🌲 wt-party")
    # ...and that hue is its own thing, not a severity color reused.
    assert THEME.wt not in (THEME.s_ok, THEME.s_warn, THEME.s_hot, THEME.mute)


def test_no_worktree_marker_for_normal_checkout():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x",
                     is_worktree=False),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "worktree" not in s.lower()


def test_color_mode_emits_ansi():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=True, use_color=True,
    )
    assert "\x1b[" in s


def test_dispatcher_appends_identity_when_enabled():
    from claude_statusbar import styles
    out = styles.render(
        "classic",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=True,
        identity=IdentityInfo(project_name="demo", in_git=True,
                              branch="main", detached=False,
                              worktree_name=None, toplevel="/x"),
        identity_dirty=False,
    )
    assert "\n" in out
    second = out.split("\n", 1)[1]
    assert "demo" in second and "main" in second


def test_dispatcher_omits_identity_when_disabled():
    from claude_statusbar import styles
    out = styles.render(
        "classic",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=False,
    )
    assert "\n" not in out


def test_identity_line_shows_duration_and_lines():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, duration_text="1h12m", lines_text="+235",
        use_color=False,
    )
    assert "proj" in s and "main" in s
    assert "⏱" in s and "1h12m" in s
    assert "+235" in s


def test_identity_line_lines_diff_colored():
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, lines_text="+41 -15", use_color=True,
    )
    from claude_statusbar.styles import _fg
    assert _fg(THEME.s_ok) in s    # +41 green
    assert _fg(THEME.s_hot) in s   # -15 red


def test_identity_line_lines_before_duration():
    # Lines (productivity) read first; the weaker duration signal trails it.
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, duration_text="1h12m", lines_text="+235",
        use_color=False,
    )
    assert s.index("+235") < s.index("1h12m")


def test_identity_line_no_stats_when_absent():
    s = render_identity_line(
        IdentityInfo(project_name="p", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x"),
        theme=THEME, dirty=False, use_color=False,
    )
    assert "⏱" not in s


def test_dispatcher_applies_to_capsule_too():
    from claude_statusbar import styles
    out = styles.render(
        "capsule",
        msgs_pct=10, weekly_pct=20, model="Opus 4.7",
        reset_5h="4h", reset_7d="6d",
        use_color=False, theme=THEME,
        show_project_branch=True,
        identity=IdentityInfo(project_name="demo", in_git=True,
                              branch="main", detached=False,
                              worktree_name=None, toplevel="/x"),
        identity_dirty=False,
    )
    assert "demo" in out and "main" in out


def _info():
    return IdentityInfo(project_name="proj", in_git=True, branch="main",
                        detached=False, worktree_name=None, toplevel="/x")


def test_version_appended_at_end_no_color():
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             version_text="3.11.2", use_color=False)
    assert s.endswith("· v3.11.2")          # the very end of the line


def test_version_omitted_when_blank():
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             version_text="", use_color=False)
    assert "v3.11.2" not in s and "· v" not in s


def test_version_is_faint_and_dim_grey_in_color():
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             version_text="3.11.2", use_color=True)
    # faint attribute (2m) + edge (darkest grey) immediately before the version
    assert "\033[2m" in s
    edge = THEME.edge
    assert f"\033[2m\033[38;2;{edge[0]};{edge[1]};{edge[2]}m· v3.11.2" in s


def test_show_version_config_default_on():
    from claude_statusbar.config import StatusbarConfig
    assert StatusbarConfig().show_version is True


def test_update_hint_appended_when_newer(tmp_path):
    from claude_statusbar.styles import render_identity_line, _update_hint, _statusbar_version
    import json, time
    p = tmp_path / "latest.json"
    cur = _statusbar_version() or "0.0.0"
    newer = ".".join(str(int(x) + (1 if i == 0 else 0)) for i, x in enumerate((cur.split(".") + ["0", "0"])[:3]))
    p.write_text(json.dumps({"version": newer, "checked_at": time.time()}))
    assert _update_hint(path=p) == newer
    s = render_identity_line(_info(), theme=THEME, dirty=False,
                             version_text=cur, update_text=newer, use_color=False)
    assert s.endswith(f"↑{newer}")


def test_update_hint_blank_when_uptodate(tmp_path):
    from claude_statusbar.styles import _update_hint, _statusbar_version
    import json, time
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"version": _statusbar_version() or "0.0.0", "checked_at": time.time()}))
    assert _update_hint(path=p) == ""


def test_update_hint_blank_when_stale(tmp_path):
    from claude_statusbar.styles import _update_hint
    import json
    p = tmp_path / "latest.json"
    p.write_text(json.dumps({"version": "999.0.0", "checked_at": 0}))  # ancient check
    assert _update_hint(path=p) == ""


def test_update_hint_blank_when_missing(tmp_path):
    from claude_statusbar.styles import _update_hint
    assert _update_hint(path=tmp_path / "nope.json") == ""


def test_main_checkout_shows_the_worktree_count():
    # Silence in the main checkout was indistinguishable from "the feature is
    # broken" — asked three times in one session. The count is the useful half.
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x",
                     is_worktree=False, worktree_count=3),
        theme=THEME, dirty=False, use_color=False,
    )
    assert s.startswith("🌲 trunk (3) ⤷ proj")
    # Same tree glyph as a worktree; "trunk" is what says which tree you're in.
    assert "trunk" in s


def test_main_checkout_reports_zero_explicitly():
    # An absent marker and a zero count look the same; "is it broken or is it
    # zero?" got asked four times. Say zero.
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x",
                     is_worktree=False, worktree_count=0),
        theme=THEME, dirty=False, use_color=False,
    )
    assert s.startswith("🌲 trunk (0) ⤷ proj")


def test_no_marker_outside_a_git_repo():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=False, branch=None,
                     detached=False, worktree_name=None, toplevel=None,
                     is_worktree=False, worktree_count=0),
        theme=THEME, dirty=None, use_color=False,
    )
    assert "🌲" not in s
    assert "(no git)" in s


def test_main_checkout_marker_is_dimmed_not_shouting():
    s = render_identity_line(
        IdentityInfo(project_name="proj", in_git=True, branch="main",
                     detached=False, worktree_name=None, toplevel="/x",
                     is_worktree=False, worktree_count=2),
        theme=THEME, dirty=False, use_color=True,
    )
    r, g, b = THEME.wt
    assert s.startswith(f"\033[2m\033[38;2;{r};{g};{b}m🌲 trunk (2)")
