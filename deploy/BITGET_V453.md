# Bitget V4.5.3 实盘控制台

这套部署冻结原始 V4.5.3 信号源码，版本提交为 `39d0675f350ae40caba4b4025b091e7df61bd2a5`，配置为 `configs/v4_5_3_params.json`。GUI 通过 `/bitget` 提供配置、只读预检、启动、停止和紧急平仓。

## 服务器部署

```bash
git fetch origin xuyujian-bitget-v453
git switch xuyujian-bitget-v453
git pull --ff-only origin xuyujian-bitget-v453
source .venv/bin/activate
pip install -e .
python -m py_compile deploy/demo_gui.py deploy/bitget_v453_ui.py deploy/bitget_v453_runner.py
python -m pytest tests/test_bitget_v453_runner.py tests/test_bitget_uta.py -q
tmux kill-session -t btc-gui 2>/dev/null || true
tmux new-session -d -s btc-gui 'cd ~/Binance-BTC && source .venv/bin/activate && exec python deploy/demo_gui.py'
```

原 GUI 只监听 `127.0.0.1:8080`，通过本地 SSH 隧道访问：

```powershell
ssh -N -L 8080:127.0.0.1:8080 ubuntu@服务器公网IP
```

浏览器打开 `http://127.0.0.1:8080/bitget`。

## GUI 操作顺序

1. 填入 Bitget UTA 的 API Key、API Secret、Passphrase，保存。
2. 点击“只读账户预检”。预检必须确认 UTA、单向持仓、BTCUSDT 无仓位、无普通挂单、无保护单。
3. 输入 `LIVE` 后点击启动。首次启动会用官方接口设置 BTCUSDT 逐仓、7x，并再次读取设置确认。
4. 普通开仓/增加敞口为 `post_only` 限价 Maker，60 分钟后撤单；减仓、反向先平旧仓、交易所止盈止损为市价 Taker。POST 超时不会自动重复下单，会按 `clientOid` 对账。
5. 停止策略只停止循环并取消本策略未成交 Maker 单，保留仓位和保护单。输入 `CLOSE` 才会撤销本策略订单、提交 reduce-only 市价平仓，并确认仓位归零。

API 凭证和运行状态只写入被 Git 忽略的 `runtime/bitget_v453/`。不要提交或复制该目录。建议专用 Bitget UTA 账户只运行这一套 BTCUSDT 策略，避免人工仓位和其他机器人混在同一单向持仓中。

行情使用 Bitget 官方 UTA v3 已收盘 `1H` K 线、标记价 K 线和公开 v2 历史资金费率。实盘不使用回测的 2% 分钟参与率或历史返佣假设；公开接口查询到的数量步长、价格步长、最低成交额会在每次循环动态读取。Maker 队列和部分成交无法与 OHLC 回测完全相同。

这套代码已完成本地接口模拟测试；没有 API 凭证时不会启动实盘，也不会通过预检或市场数据请求下单。
