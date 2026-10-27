import os

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
    monkeypatch.setattr(ui.runner, "cancel_pending_entry", lambda: None)
    result = ui._stop()
    assert "未发现本策略遗留 Maker 挂单" in result
    assert "现有仓位和交易所保护单仍保留" in result


def test_stop_finds_runner_pid_from_lock_when_gui_pid_is_stale(tmp_path, monkeypatch):
    lock = tmp_path / "runner.lock"
    lock.write_text("777", encoding="ascii")
    process = tmp_path / "process.json"
    process.write_text('{"pid":111}')
    monkeypatch.setattr(ui, "PROCESS", process)
    monkeypatch.setattr(ui.runner, "LOCK", lock)
    alive = {777}
    killed = []
    monkeypatch.setattr(ui, "_alive", lambda pid: int(pid) in alive)
    def fake_kill(pid, _sig):
        killed.append(pid)
        alive.discard(pid)
    monkeypatch.setattr(ui.os, "kill", fake_kill)
    monkeypatch.setattr(ui.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ui.runner, "cancel_pending_entry", lambda: ["v453-old"])
    result = ui._stop()
    assert killed == [777]
    assert "策略已停止" in result
    assert "未成交 Maker 挂单已取消" in result


def test_unrelated_live_pid_is_not_treated_as_the_strategy_process():
    if os.name == "posix":
        assert ui._alive(os.getpid()) is False


def test_start_does_not_report_success_if_runner_exits_immediately(tmp_path, monkeypatch):
    class DeadProcess:
        pid = 987654
        def poll(self): return 2
    monkeypatch.setattr(ui.runner, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(ui, "PROCESS", tmp_path / "process.json")
    monkeypatch.setattr(ui, "LOG", tmp_path / "runner.log")
    monkeypatch.setattr(ui.runner, "preflight", lambda: {"ready": True})
    monkeypatch.setattr(ui.subprocess, "Popen", lambda *args, **kwargs: DeadProcess())
    monkeypatch.setattr(ui, "_alive", lambda _pid: False)
    monkeypatch.setattr(ui.time, "sleep", lambda _seconds: None)
    try:
        ui._start({"confirm_live": ["LIVE"]})
    except RuntimeError as exc:
        assert "立即退出" in str(exc)
    else:
        raise AssertionError("GUI reported a dead runner as started")


def test_stopped_state_marks_pending_order_and_error_as_saved_snapshot(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text('{"pending_order":{"clientOid":"v453-old"},"error":"old error"}')
    process = tmp_path / "process.json"
    process.write_text('{"pid":123}')
    monkeypatch.setattr(ui.runner, "STATE", state)
    monkeypatch.setattr(ui, "PROCESS", process)
    monkeypatch.setattr(ui, "_alive", lambda _pid: False)
    summary = ui._state_summary()
    assert "上次保存的状态快照" in summary
    assert "状态记录的 Maker 挂单（请核对交易所）" in summary
    assert "上次错误：old error" in summary


def test_render_escapes_message_and_includes_confirmation():
    page = ui.render("<unsafe>", "csrf-token")
    assert "&lt;unsafe&gt;" in page
    assert 'pattern="LIVE"' in page
    assert 'pattern="CLOSE"' in page
    assert "csrf-token" in page
