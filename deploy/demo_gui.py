#!/usr/bin/env python3
"""Dependency-free Binance Futures Demo configuration/health GUI."""
import hashlib, hmac, json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://demo-fapi.binance.com"
HOST = os.getenv("BTC_GUI_HOST", "127.0.0.1")
PORT = int(os.getenv("BTC_GUI_PORT", "8080"))
CONFIG = Path(os.getenv("BTC_GUI_CONFIG", "runtime/demo_accounts.json"))
STRATEGIES = {"v43": ("V4.3", "main", "configs/v4_3_params.json"), "v71": ("V7.1", "xuyujian修改", "configs/v71_params.json"), "v72": ("V7.2", "Binance-BTC-wzy", "configs/wzy_v72_tp_refined_params.json")}

def load():
    if CONFIG.exists(): return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {k: {"api_key":"", "api_secret":"", "symbol":"BTCUSDT", "margin_type":"ISOLATED", "leverage":2} for k in STRATEGIES}
def save(x):
    CONFIG.parent.mkdir(parents=True, exist_ok=True); os.chmod(CONFIG.parent, 0o700)
    t=CONFIG.with_suffix('.tmp'); t.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding='utf-8'); os.chmod(t,0o600); t.replace(CONFIG)
def account(c):
    q=f"timestamp={int(time.time()*1000)}&recvWindow=5000"; sig=hmac.new(c['api_secret'].encode(),q.encode(),hashlib.sha256).hexdigest()
    r=Request(BASE_URL+"/fapi/v2/account?"+q+"&signature="+sig,headers={"X-MBX-APIKEY":c['api_key']})
    with urlopen(r,timeout=10) as x: return json.loads(x.read().decode())
def page(msg=''):
    cards=[]; cfg=load()
    for k,(n,b,p) in STRATEGIES.items():
        c=cfg[k]; cards.append(f"<section><h2>{n}（{b}）</h2><p>参数：{p}</p><label>API Key <input name='{k}_api_key' value='{c.get('api_key','')}'></label><br><label>API Secret <input type='password' name='{k}_api_secret' value='{c.get('api_secret','')}'></label><br><label>合约 <input name='{k}_symbol' value='{c.get('symbol','BTCUSDT')}'></label><br><label>逐仓杠杆 <input name='{k}_leverage' type='number' min='1' max='20' value='{c.get('leverage',2)}'></label><br><a href='/check/{k}'>检查 Demo 账户</a></section>")
    return "<meta charset='utf-8'><style>body{font:15px sans-serif;max-width:900px;margin:30px auto}section{border:1px solid #ddd;padding:15px;margin:10px 0}input{width:320px;padding:5px}label{line-height:2.3}</style><h1>Binance Futures Demo 三策略控制台</h1><p>固定 API：<code>"+BASE_URL+"</code>。不会连接主网。</p><p>"+msg+"</p><form method='post' action='/save'>"+''.join(cards)+"<button>保存配置</button></form>"
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        p=urlparse(self.path); msg=''
        if p.path.startswith('/check/'):
            k=p.path.split('/')[-1]
            try: msg='连接成功：'+json.dumps(account(load()[k]).get('totalWalletBalance'),ensure_ascii=False)
            except Exception as e: msg='连接失败：'+str(e)
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(page(msg).encode())
    def do_POST(self):
        n=int(self.headers.get('Content-Length','0')); d=parse_qs(self.rfile.read(n).decode()); x=load()
        for k in STRATEGIES: x[k]={"api_key":d.get(k+'_api_key',[''])[0].strip(),"api_secret":d.get(k+'_api_secret',[''])[0],"symbol":d.get(k+'_symbol',['BTCUSDT'])[0].strip().upper(),"margin_type":"ISOLATED","leverage":int(d.get(k+'_leverage',['2'])[0])}
        save(x); self.send_response(303); self.send_header('Location','/'); self.end_headers()
if __name__=='__main__': print(f'GUI: http://{HOST}:{PORT}'); ThreadingHTTPServer((HOST,PORT),H).serve_forever()
