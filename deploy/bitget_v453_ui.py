"""Bitget V4.5.3 controls embedded in the existing server GUI."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlencode

from deploy import bitget_v453_runner as runner

ROOT = Path(__file__).resolve().parents[1]
CONFIG = runner.CONFIG
PROCESS = Path("runtime/bitget_v453/process.json")
LOG = Path("runtime/logs/bitget-v453.log")


def _config():
    return runner.read_json(CONFIG)


def _process():
    return runner.read_json(PROCESS)


def _alive(pid):
    try:
        pid = int(pid)
        os.kill(pid, 0)
        if os.name == "posix":
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
            if not cmdline or b"deploy/bitget_v453_runner.py" not in cmdline:
                return False
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
            if len(stat) > 2 and stat[2] == "Z":
                return False
        return True
    except (OSError, ValueError, TypeError):
        return False


def _active_runner_pids():
    candidates = [_process().get("pid")]
    try:
        candidates.append(runner.LOCK.read_text(encoding="ascii").strip())
    except FileNotFoundError:
        pass
    active = []
    for candidate in candidates:
        try:
            pid = int(candidate)
        except (TypeError, ValueError):
            continue
        if pid not in active and _alive(pid):
            active.append(pid)
    return active


def _terminate_runners():
    pids = _active_runner_pids()
    for pid in pids:
        os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while any(_alive(pid) for pid in pids) and time.time() < deadline:
        time.sleep(0.1)
    if any(_alive(pid) for pid in pids):
        raise RuntimeError("策略进程尚未停止")
    return pids


def _save_config(form):
    old = _config()
    values = {
        "api_key": (form.get("api_key") or [""])[0].strip(),
        "api_secret": (form.get("api_secret") or [""])[0] or old.get("api_secret", ""),
        "passphrase": (form.get("passphrase") or [""])[0] or old.get("passphrase", ""),
    }
    if not values["api_key"] or not values["api_secret"] or not values["passphrase"]:
        raise ValueError("请填写 API Key、Secret 和 Passphrase")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(CONFIG.parent, 0o700)
        os.chmod(temp, 0o600)
    temp.replace(CONFIG)


def _start(form):
    if (form.get("confirm_live") or [""])[0] != "LIVE":
        raise ValueError("输入 LIVE 后再启动实盘策略")
    state = runner.read_json(runner.STATE)
    active = _active_runner_pids()
    if active:
        return f"V4.5.3 已在运行，PID {active[0]}。"
    report = runner.preflight()
    if not state.get("initialized") and not report["ready"]:
        raise ValueError("首次启动未通过只读预检。请确认 UTA、单向持仓、BTCUSDT 无仓位和无挂单。")
    if state.get("initialized"):
        own_open = all(str(x.get("clientOid", "")).startswith(runner.OWN_PREFIX)
                       for x in report.get("open_order_details", []))
        own_strategy = all(str(x.get("clientOid", "")).startswith(runner.PROTECT_PREFIX)
                           for x in report.get("strategy_order_details", []))
        if report.get("account_mode") not in {"unified", "hybrid"} or report.get("hold_mode") != "one_way_mode":
            raise ValueError("账户模式与已初始化状态不符，已停止启动")
        if not own_open or not own_strategy:
            raise ValueError("发现非本策略挂单/止盈止损单，先在 Bitget 核实并处理")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG, "a", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "deploy/bitget_v453_runner.py"], cwd=ROOT,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    time.sleep(0.25)
    if process.poll() is not None or not _alive(process.pid):
        tail = ""
        try:
            tail = "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
        except OSError:
            pass
        raise RuntimeError("Runner 启动后立即退出；未报告为运行中。请检查日志：" + tail[-1200:])
    runner.write_json(PROCESS, {"pid": process.pid, "started_at": int(time.time()), "strategy": "V4.5.3"})
    return f"V4.5.3 实盘已启动，PID {process.pid}。按最近一根已收盘小时 K 线的信号运行，不读取未完成 K 线。"


def _stop():
    stopped = _terminate_runners()
    cancelled = runner.cancel_pending_entry()
    PROCESS.unlink(missing_ok=True)
    prefix = "策略已停止；" if stopped else "策略当前未运行；"
    return prefix + ("本策略未成交 Maker 挂单已取消。" if cancelled else "未发现本策略遗留 Maker 挂单。") + "现有仓位和交易所保护单仍保留。"


def _flatten(form):
    if (form.get("confirm_close") or [""])[0] != "CLOSE":
        raise ValueError("输入 CLOSE 才会撤销本策略挂单并市价平掉 BTCUSDT 仓位")
    _terminate_runners()
    PROCESS.unlink(missing_ok=True)
    result = runner.flatten()
    return "已提交平仓操作：" + json.dumps(result, ensure_ascii=False)


def dispatch(action, form):
    try:
        if action == "save":
            _save_config(form)
            return "API 配置已加密通道传输并以仅当前用户可读权限保存在服务器。"
        if action == "preflight":
            report = runner.preflight()
            runner.write_json(Path("runtime/bitget_v453/preflight.json"), report)
            status = "通过" if report["ready"] else "未通过"
            return f"只读预检{status}：UTA={report['account_mode']}，持仓模式={report['hold_mode']}，USDT权益={report['usdt_equity']}，可用USDT={report['available_usdt']}，仓位/普通挂单/保护单={len(runner.response_list(report['positions']))}/{report['open_orders']}/{report['strategy_orders']}。未调整账户、未下单。"
        if action == "start":
            return _start(form)
        if action == "stop":
            return _stop()
        if action == "flatten":
            return _flatten(form)
        raise ValueError("Unknown Bitget action")
    except Exception as exc:
        return str(exc)[:700]


def _state_summary():
    state = runner.read_json(runner.STATE)
    active = _active_runner_pids()
    running = bool(active)
    status = f"运行中 PID {active[0]}" if running else "未运行（以下为上次保存的状态快照）"
    if not state:
        return status + "；尚无策略状态"
    error_label = "最近错误" if running else "上次错误"
    rows = [status, f"最近完成 K 线：{state.get('last_bar', '尚无')}",
            f"信号：{state.get('last_signal', '尚无')}，目标 BTC：{state.get('target_qty', '尚无')}，当前 BTC：{state.get('current_qty', '尚无')}",
            f"USDT 权益：{state.get('equity', '尚无')}，标记价格：{state.get('mark_price', '尚无')}",
            f"逐仓 / 杠杆：{state.get('margin_mode', '尚未验证')} / {state.get('leverage', '尚未验证')}x"]
    if state.get("pending_order"):
        prefix = "Maker 挂单" if running else "状态记录的 Maker 挂单（请核对交易所）"
        rows.append(prefix + "：" + str(state["pending_order"].get("clientOid")))
    if state.get("error"):
        rows.append(error_label + "：" + str(state["error"]))
    return "<br>".join(html.escape(x) for x in rows)


def render(message, csrf):
    saved = _config()
    msg = f"<p class='message'>{html.escape(message)}</p>" if message else ""
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bitget V4.5.3</title><style>
body{{font:15px system-ui,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#17212b;background:#f5f7f8}}
header,section{{background:white;border:1px solid #d9e0e4;border-radius:6px;padding:18px;margin-bottom:14px}}
h1{{font-size:22px;margin:0 0 6px}}h2{{font-size:17px;margin:0 0 14px}}p{{line-height:1.55}}.muted{{color:#586873}}.warning{{color:#8a3d12;background:#fff3e7;padding:10px;border-left:3px solid #d66a23}}
label{{display:block;margin:10px 0 4px}}input{{box-sizing:border-box;width:min(100%,480px);padding:9px;border:1px solid #aab6bd;border-radius:4px;font:inherit}}
button{{padding:9px 14px;margin:8px 8px 0 0;border:1px solid #657680;border-radius:4px;background:#fff;color:#17212b;font:inherit;cursor:pointer}}button.primary{{background:#126b57;border-color:#126b57;color:#fff}}button.danger{{background:#a33127;border-color:#a33127;color:#fff}}.message{{padding:10px;background:#e7f3ef;border-left:3px solid #18836a}}
code{{background:#edf1f3;padding:2px 4px}}a{{color:#136a57}}.actions{{display:flex;gap:10px;flex-wrap:wrap}}.actions form{{margin:0}}small{{color:#586873}}
</style><body><header><a href="/">返回 Binance Demo GUI</a><h1>V4.5.3 · Bitget UTA 实盘</h1><div class="muted">BTCUSDT USDT 永续 · 独立策略账户配置</div></header>
{msg}<section><h2>运行状态</h2><p>{_state_summary()}</p><p class="warning">实盘操作会影响真实资金。策略按冻结信号计算目标名义仓位（最高约 4 倍权益），交易所逐仓杠杆设为 7 倍；不设额外投入金额上限。开始前请使用专用且 BTCUSDT 无其他人工挂单的 UTA 账户。</p></section>
<section><h2>Bitget API</h2><form method="post" action="/bitget/save"><input type="hidden" name="csrf" value="{html.escape(csrf)}">
<label>API Key</label><input name="api_key" autocomplete="off" value="{html.escape(saved.get('api_key',''))}" required>
<label>API Secret</label><input type="password" name="api_secret" autocomplete="new-password" placeholder="留空则保留服务器已保存的值">
<label>Passphrase</label><input type="password" name="passphrase" autocomplete="new-password" placeholder="留空则保留服务器已保存的值">
<p><small>凭证经 SSH 隧道传输，保存在服务器 <code>runtime/bitget_v453/config.json</code>，权限仅限运行用户；不要把密钥发到聊天中。</small></p><button>保存凭证</button></form></section>
<section><h2>操作</h2><div class="actions">
<form method="post" action="/bitget/preflight"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><button>只读账户预检</button></form>
<form method="post" action="/bitget/start"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><label>输入 LIVE 启动实盘</label><input name="confirm_live" autocomplete="off" pattern="LIVE" required><button class="primary">启动 V4.5.3</button></form>
<form method="post" action="/bitget/stop"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><button>停止策略</button></form>
<form method="post" action="/bitget/flatten"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><label>输入 CLOSE 撤单并市价平仓</label><input name="confirm_close" autocomplete="off" pattern="CLOSE" required><button class="danger">紧急平仓</button></form></div>
<p class="muted">普通开仓和增加仓位采用 post-only Maker，最长等待 60 分钟；减仓和止盈止损由 Taker 市价执行。停止策略不会平仓，现有交易所止盈止损继续有效。紧急平仓只处理本策略 clientOid 的挂单及该专用账户的 BTCUSDT 仓位。</p></section>
<section><h2>冻结策略与执行参数</h2><p>策略源码：V4.5.3 commit <code>{runner.SOURCE_COMMIT}</code>；信号参数：<code>configs/v4_5_3_params.json</code>；账户：UTA 单向持仓、逐仓、7x；市场数据：Bitget 已收盘小时 K 线、4 小时/日线因果聚合与已结算资金费率。</p><p class="muted">实盘 Maker 队列、部分成交和费用与回测 OHLC 模拟不同。回测的 2% 分钟流动性限制、历史返佣不用于实盘下单。</p></section></body></html>"""
