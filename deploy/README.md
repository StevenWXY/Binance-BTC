# Binance Futures Demo 三策略控制台

固定使用 U 本位合约 Demo：`https://demo-fapi.binance.com`。

策略映射：V4.3=`main` + `configs/v4_3_params.json`；V7.1=`xuyujian修改` + `configs/v71_params.json`；V7.2=`Binance-BTC-wzy` + `configs/wzy_v72_tp_refined_params.json`。

启动：`python deploy/demo_gui.py`，浏览器打开 `http://服务器IP:8080`。可通过 `BTC_GUI_HOST`、`BTC_GUI_PORT` 环境变量修改监听地址和端口。API Secret 仅保存到服务器本地 `runtime/demo_accounts.json`，不得上传 GitHub。
