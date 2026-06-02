from claude_statusbar.config import StatusbarConfig, load_config, set_value


def test_default_on():
    assert StatusbarConfig().show_forecast is True

def test_set_and_load(tmp_path):
    p = tmp_path / "cfg.json"
    set_value("show_forecast", "false", p)
    assert load_config(p).show_forecast is False

def test_forecast_debug_default_off():
    assert StatusbarConfig().forecast_debug is False

def test_forecast_debug_set_and_load(tmp_path):
    p = tmp_path / "cfg.json"
    set_value("forecast_debug", "true", p)
    assert load_config(p).forecast_debug is True
