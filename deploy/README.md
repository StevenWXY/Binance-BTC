# Binance Futures Demo 三策略控制台

固定使用 U 本位合约 Demo：`https://demo-fapi.binance.com`。

策略映射：V4.3=`main` + `configs/v4_3_params.json`；V7.1=`xuyujian修改` + `configs/v71_params.json`；V7.2=`Binance-BTC-wzy` + `configs/wzy_v72_tp_refined_params.json`。

启动：`python deploy/demo_gui.py`，浏览器打开 `http://服务器IP:8080`。可通过 `BTC_GUI_HOST`、`BTC_GUI_PORT` 环境变量修改监听地址和端口。API Secret 仅保存到服务器本地 `runtime/demo_accounts.json`，不得上传 GitHub。
# Demo runner update

The GUI now manages the three Demo runners. It always uses
`https://demo-fapi.binance.com`, never a mainnet URL. V4.3, V7.1, and V7.2
keep their respective checked-in parameter files; V7.2's own execution
drawdown Governor is isolated to V7.2 and never applied to V4.3 or V7.1.

The GUI's Start button launches `deploy/demo_runner.py`. The runner uses only
completed 4h candles, sets BTCUSDT to isolated margin and the leverage needed
by the original strategy profile, reconciles the BTCUSDT position through
Demo API market orders, and refreshes its status once per minute. The V7.2
default test capital cap is 4000 USDT; this is a deployment test limit, not a
change to the V7.2 parameter file. Emergency close stops the runner first and
then submits a reduce-only market order.

Use three independent Demo accounts for three strategies. Do not put two
runners on the same BTCUSDT position. Runtime credentials, process status and
logs are stored under git-ignored `runtime/` and must never be committed.
