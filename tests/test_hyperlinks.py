"""Clickable (OSC 8) links on aurora's lower lines and risk rows."""
from types import SimpleNamespace

import pytest

from claude_statusbar import identity
from claude_statusbar._display import clip_line, hyperlink, visible_width
from claude_statusbar.styles import render_identity_line_aurora
from claude_statusbar.themes import get_theme

THEME = get_theme("graphite")
REPO = "https://github.com/o/r"


@pytest.mark.parametrize("url", [None, "", "javascript:alert(1)", "file:///etc/passwd",
                                 "https://x/\x1b]8;;evil", "https://x/a b", "https://x/\x07"])
def test_unsafe_urls_stay_plain(url):
    assert hyperlink("txt", url) == "txt"


def test_link_has_no_width_and_clip_closes_it():
    s = "ab " + hyperlink("linked-text", REPO) + " tail"
    assert visible_width(s) == len("ab linked-text tail")
    cut = clip_line(s, 8)
    assert visible_width(cut) == 8
    assert cut.count("\x1b]8;;\x07") == 1 and cut.endswith("\x1b]8;;\x07")


def _info(**kw):
    base = dict(project_name="r", in_git=True, branch="feat/x", detached=False,
                is_worktree=False, worktree_count=0, worktree_name=None, web_url=REPO)
    base.update(kw)
    return SimpleNamespace(**base)


def test_identity_line_links_repo_branch_and_release():
    out = render_identity_line_aurora(_info(), theme=THEME, dirty=False,
                                      version_text="3.49.2", update_text="3.49.3")
    assert f"\x1b]8;;{REPO}\x07" in out
    assert f"\x1b]8;;{REPO}/tree/feat/x\x07" in out
    assert "releases/tag/v3.49.3\x07" in out


def test_no_links_in_plain_text_or_without_remote():
    plain = render_identity_line_aurora(_info(), theme=THEME, dirty=False, use_color=False)
    assert "\x1b" not in plain
    out = render_identity_line_aurora(_info(web_url=None), theme=THEME, dirty=False)
    assert "\x1b]8" not in out


@pytest.mark.parametrize("remote,expected", [
    ("git@github.com:o/r.git", "https://github.com/o/r"),
    ("ssh://git@gitlab.example.com:2222/g/s/p.git", "https://gitlab.example.com/g/s/p"),
    ("https://user:token@github.com/o/r.git", "https://github.com/o/r"),
    ("https://github.com/o/r/", "https://github.com/o/r"),
    ("git@host:../etc", None),
    ("file:///tmp/repo", None),
    ("/local/path/repo.git", None),
])
def test_remote_web_url(remote, expected):
    assert identity.remote_web_url(remote) == expected


def test_branch_url_per_forge():
    assert identity.branch_web_url("https://gitlab.com/g/p", "a b") == "https://gitlab.com/g/p/-/tree/a%20b"
    assert identity.branch_web_url("https://bitbucket.org/o/r", "m") == "https://bitbucket.org/o/r/src/m"
    assert identity.branch_web_url(None, "m") is None


def test_reads_origin_from_config_and_worktree_commondir(tmp_path):
    main = tmp_path / "main" / ".git"
    main.mkdir(parents=True)
    (main / "HEAD").write_text("ref: refs/heads/main\n")
    (main / "config").write_text(
        '[remote "upstream"]\n\turl = git@github.com:up/r.git\n'
        '[remote "origin"]\n\turl = https://u:SECRET@github.com/me/r.git\n')
    assert identity._read_web_url(tmp_path / "main") == "https://github.com/me/r"
    wt_git = main / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "commondir").write_text("../..\n")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_git}\n")
    assert identity._read_web_url(wt) == "https://github.com/me/r"
