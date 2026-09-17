"""Exploratory 15-minute mean-reversion comparison, not production execution.

Conservative all-taker costs: 4 bps * (1-40%) + 1 bps slippage per side.
Stop first if both barriers are touched, stop gaps filled at adverse open.
No queue/order-book model. Development score excludes 2025+ evaluation.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from btc_regime.data import iter_intrabar_months,load_market_data
from btc_regime.indicators import adx,atr
from btc_regime.range_grid import _efficiency_ratio

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bar-minutes',type=int,choices=[15,60],default=15)
args=parser.parse_args()
bar=args.bar_minutes
cache=Path(f'data/v8_verified_{bar}m.pkl')
if cache.exists(): d=pd.read_pickle(cache)
else:
 parts=[]; audit=[]; last=None
 for m in iter_intrabar_months('data/v8_verified',start='2020-01-01',end='2026-08-01'):
  if last is not None and m.index[0]<=last: raise ValueError('overlapping minute data')
  audit.append({'start':str(m.index[0]),'end':str(m.index[-1]),'rows':len(m),'gaps':int((m.index.to_series().diff().dropna()!=pd.Timedelta(minutes=1)).sum())})
  last=m.index[-1]
  q=m.rename(columns={x:'%s'%x.removeprefix('trade_') for x in m.columns if x.startswith('trade_')})
  p=q.resample(f'{bar}min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','quote_volume':'sum'})
  p['minute_count']=q.close.resample(f'{bar}min').count()
  parts.append(p)
 d=pd.concat(parts); d.to_pickle(cache)
 Path('reports/v8_research').mkdir(exist_ok=True)
 Path(f'reports/v8_research/repaired_minute_coverage_{bar}min.json').write_text(json.dumps(audit,indent=2))
print('rows',len(d),'incomplete',(d.minute_count!=bar).sum(),flush=True)
slow=load_market_data('data/v8_verified',start='2020-01-01',end='2026-08-01')
slow['slow_adx']=adx(slow)[0]; slow['eff']=_efficiency_ratio(slow.close,12)
slow['mom']=slow.close.pct_change(3)
slow.index+=pd.Timedelta(hours=4)
# 15m features available at t+15; previous 4h close available <= t+15
features=slow[['slow_adx','eff','mom']].reindex(d.index+pd.Timedelta(minutes=bar),method='ffill');features.index=d.index
for c in features:d[c]=features[c]
d['atr']=atr(d,20)
for period in [32,64,96]:
 mid=d.close.rolling(period).mean(); sd=d.close.rolling(period).std()
 d['mid'+str(period)]=mid;d['z'+str(period)]=(d.close-mid)/sd
if __name__=='__main__':
 import itertools
 rows=[]
 for adxmax,effmax,period,entry,stopatr in itertools.product([24,30],[.35,.55],[32,64],[1.5,2.0],[2,3]):
  n=len(d); signal=np.zeros(n); side=0; size=0; stop=take=0; age=0;cool=0; entries=0
  cl=d.close.to_numpy(); op=d.open.to_numpy(); hi=d.high.to_numpy();lo=d.low.to_numpy();at=d.atr.to_numpy();mid=d['mid'+str(period)].to_numpy();z=d['z'+str(period)].to_numpy()
  allowed=(d.slow_adx.le(adxmax)&d.eff.le(effmax)&d.mom.abs().lt(.035)&d.minute_count.eq(bar)).to_numpy()
  pnl=np.zeros(n); trades=np.zeros(n)
  for i in range(1,n):
   if side:
    # evaluate existing position through completed bar, worse stop precedence
    move=side*(cl[i]/cl[i-1]-1)
    stopped=(lo[i]<=stop if side>0 else hi[i]>=stop)
    taken=(hi[i]>=take if side>0 else lo[i]<=take)
    if stopped: exitp=min(op[i],stop) if side>0 else max(op[i],stop);move=side*(exitp/cl[i-1]-1)
    elif taken: exitp=take;move=side*(exitp/cl[i-1]-1)
    pnl[i]=size*move;age+=1
    if stopped or taken or age>=32 or not allowed[i]:
     pnl[i]-=size*3.4e-4;side=0;cool=4 if stopped else 1
   if cool:cool-=1
   elif not side and allowed[i] and np.isfinite(z[i]):
    sdirection=1 if z[i]<=-entry and cl[i]>cl[i-1] else -1 if z[i]>=entry and cl[i]<cl[i-1] else 0
    if sdirection and abs(mid[i]/cl[i]-1)>.001:
     side=sdirection;age=0;size=min(2,.003/(stopatr*at[i]/cl[i]));stop=cl[i]-side*stopatr*at[i];take=mid[i];pnl[i]-=size*3.4e-4;entries+=1;trades[i]=1
   signal[i]=side*size
  out={'adx':adxmax,'eff':effmax,'period':period,'entry':entry,'stopatr':stopatr,'trades':entries}
  for label,s,e in [('train','2020-01-01','2023-01-01'),('val','2023-01-01','2025-01-01'),('eval','2025-01-01','2026-08-01')]:
   mask=(d.index>=pd.Timestamp(s,tz='UTC'))&(d.index<pd.Timestamp(e,tz='UTC'))
   ret=pnl[mask];equity=np.cumprod(1+ret);out[label]=equity[-1]-1;out[label+'_dd']=np.min(equity/np.maximum.accumulate(equity)-1);out[label+'_trades']=int(trades[mask].sum())
  out['score']=min(out['train'],out['val'])-.5*max(-out['train_dd'],-out['val_dd'])
  rows.append(out)
 table=pd.DataFrame(rows).sort_values('score',ascending=False)
 table.to_csv(f'reports/v8_research/intraday_{bar}min_exploratory.csv',index=False)
 print(table.head(15).to_string(index=False))
