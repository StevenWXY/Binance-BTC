# BTCUSDT V4.5.3 Bitget 实盘

本分支用于在腾讯轻量服务器的 GUI 中运行冻结的 V4.5.3 策略，通过 Bitget UTA API 交易 BTCUSDT USDT 本位永续合约。策略源码基于仓库原始 V4.5.3 提交 `39d0675f350ae40caba4b4025b091e7df61bd2a5`；参数见 [`configs/v4_5_3_params.json`](configs/v4_5_3_params.json)，Bitget API 与执行说明见 [`deploy/BITGET_V453.md`](deploy/BITGET_V453.md)。

## 策略与参数

- 信号：4 小时策略逻辑，包含多空方向、结构过滤、8 根 K 线突破、成交活跃度确认、ADX 最低值 32、基础保护和 3 小时冷却；风险配置为 `higher`。
- 配置文件同时记录回测执行假设：maker/taker 费率、返佣、滑点、分钟参与率和 30% 回撤限制。它们属于历史回测口径，不会全部照搬到实盘。实盘不设回测的每分钟 2% 成交限制，也不假设历史返佣。
- 账户：Bitget UTA、单向持仓、BTCUSDT 逐仓、交易所杠杆 7 倍。目标名义仓位按策略信号和实际 USDT 权益计算，不额外乘 7；实际仓位受可用保证金和交易所规则约束。
- 行情：Bitget 已收盘 1 小时 K 线、标记价格 K 线及公开历史资金费率。每轮动态读取合约精度和最小下单金额。
- 执行：开仓和加仓采用 `post_only` Maker，最长等待 60 分钟；减仓、反向平旧仓和策略保护退出使用 reduce-only 市价单。反向时先平旧方向，再建立新方向。

## 服务器更新与启动

以下命令在腾讯 Ubuntu 服务器执行。更新不会删除 `runtime/` 下的 API 配置或策略状态：

```bash
cd ~/Binance-BTC
git fetch origin xuyujian-bitget-v453
git switch xuyujian-bitget-v453 || git switch -c xuyujian-bitget-v453 --track origin/xuyujian-bitget-v453
git pull --ff-only origin xuyujian-bitget-v453
source .venv/bin/activate
pip install -e .
python -m compileall -q deploy src/btc_regime src/btc_regime_v453
python -m pytest -q
tmux kill-session -t btc-gui 2>/dev/null || true
tmux new-session -d -s btc-gui 'cd ~/Binance-BTC && source .venv/bin/activate && exec python deploy/demo_gui.py'
curl -sS http://127.0.0.1:8080/bitget | head
```

GUI 仅监听服务器本机 `127.0.0.1:8080`。在本地电脑另开终端建立 SSH 隧道，并保持该窗口运行：

```powershell
ssh -N -L 8080:127.0.0.1:8080 ubuntu@服务器公网IP
```

浏览器访问 `http://127.0.0.1:8080/bitget`。

## GUI 操作

1. 填写 Bitget UTA API Key、Secret 和 Passphrase，保存。API 只需合约读取和交易权限，关闭提现权限，并建议设置服务器 IP 白名单。
2. 点击“只读账户预检”。预检要求 UTA、单向持仓，且 BTCUSDT 无持仓、普通挂单和保护单。当前若显示 `hedge_mode`，需先在 Bitget 合约账户设置切换为单向持仓，再重新预检。
3. 预检通过后，输入 `LIVE` 并点击“启动 V4.5.3”。这会启动真实账户交易；首次启动会通过 API 设置 BTCUSDT 逐仓和 7 倍杠杆。
4. “停止策略”会停止 runner 并尝试撤销本策略未成交 Maker 挂单，但保留仓位和交易所保护单。紧急平仓需输入 `CLOSE`，会撤销本策略挂单、提交 reduce-only 市价平仓并确认仓位归零。

**重要：保存 API 或运行只读预检不会下单；输入 `LIVE` 启动后可能根据最新已收盘 K 线信号开始交易。实盘会影响真实资金。** 启动前确认 API 环境、账户、保证金和仓位均符合预期。不要将 API 凭证发送到聊天、提交到 Git 或放入 `runtime/` 以外的文件。

凭证及运行状态保存在 Git 忽略的 `runtime/bitget_v453/`。建议该 UTA 账户专供此策略使用，避免人工交易或其他机器人共享 BTCUSDT 单向仓位。
