from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_default_off():
    assert StatusbarConfig().show_project_branch is False


def test_set_via_set_value(tmp_path):
    p = tmp_path / "c.json"
    cfg = set_value("show_project_branch", "true", path=p)
    assert cfg.show_project_branch is True
    assert load_config(p).show_project_branch is True


def test_set_off(tmp_path):
    p = tmp_path / "c.json"
    set_value("show_project_branch", "true", path=p)
    cfg = set_value("show_project_branch", "off", path=p)
    assert cfg.show_project_branch is False


def test_cli_accepts_show_project_branch_key():
    """cs config set <key> rejects unknown keys with KeyError. Ensure the
    new key passes the VALID_KEYS gate so the cli surface is wired."""
    from claude_statusbar.config import VALID_KEYS
    assert "show_project_branch" in VALID_KEYS
