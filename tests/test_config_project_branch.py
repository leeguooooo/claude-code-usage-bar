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
