from urllib.parse import parse_qs

from deploy import bitget_v453_ui as ui


def test_save_keeps_existing_secret_when_password_fields_empty(tmp_path, monkeypatch):
    config = tmp_path / "runtime" / "config.json"
    config.parent.mkdir()
    config.write_text('{"api_key":"old-key","api_secret":"old-secret","passphrase":"old-pass"}')
    monkeypatch.setattr(ui, "CONFIG", config)
    ui._save_config({"api_key": ["new-key"], "api_secret": [""], "passphrase": [""]})
    assert ui._config() == {"api_key": "new-key", "api_secret": "old-secret", "passphrase": "old-pass"}


def test_start_requires_explicit_live_word(monkeypatch):
    called = []
    monkeypatch.setattr(ui.runner, "preflight", lambda: called.append("preflight"))
    try:
        ui._start({"confirm_live": [""]})
    except ValueError as exc:
        assert "LIVE" in str(exc)
    else:
        raise AssertionError("live start without confirmation was accepted")
    assert called == []


def test_stop_flattens_nothing(monkeypatch):
    monkeypatch.setattr(ui, "_process", lambda: {"pid": 123})
    monkeypatch.setattr(ui, "_alive", lambda _pid: False)
    result = ui._stop()
    assert "未改变" in result


def test_render_escapes_message_and_includes_confirmation():
    page = ui.render("<unsafe>", "csrf-token")
    assert "&lt;unsafe&gt;" in page
    assert 'pattern="LIVE"' in page
    assert 'pattern="CLOSE"' in page
    assert "csrf-token" in page
