"""V8 execution, leverage, no-addition and V4-complement comparisons.

Uses one repaired archive view and identical costs for every strategy. V4
has priority on one net position; V8's stop/take levels travel with its signal.
No live trading is performed. Evaluation is exploratory, not an unseen test.
"""
from __future__ import annotations
import argparse
from dataclasses import replace,asdict
import json
from pathlib import Path
import numpy as np
import pandas as pd
from btc_regime.data import load_market_data,load_funding,iter_intrabar_months
from btc_regime.v8 import V8Params,generate_v8_signals,route_v4_v8_signals
from btc_regime.v43 import V43Params,generate_v43_signals
from btc_regime.micro_backtest import MicroBacktestConfig,run_micro_backtest,write_micro_report,micro_period_metrics


def frequency(trades,start,end):
    entries=pd.to_datetime(trades.entry_time,utc=True).sort_values() if len(trades) else pd.DatetimeIndex([])
    boundaries=pd.DatetimeIndex([pd.Timestamp(start,tz='UTC'),*entries,pd.Timestamp(end,tz='UTC')])
    gaps=np.diff(boundaries.asi8)/86400e9
    years=(pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()/86400/365.25
    return {'entries_per_month':len(entries)/(years*12),'max_days_between_entries':float(gaps.max()),
            'median_days_between_entries':float(np.median(gaps)),
            'months_with_no_entry':int((pd.Series(1,index=entries).resample('MS').sum().reindex(pd.date_range(start,pd.Timestamp(end)-pd.Timedelta(days=1),freq='MS',tz='UTC'),fill_value=0)==0).sum())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',default='data/v8_verified')
    parser.add_argument('--output',default='reports/v8_final')
    parser.add_argument('--params',default='configs/v8_params.json')
    parser.add_argument('--only',nargs='+',help='run named cases and merge into the existing report')
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(exist_ok=True,parents=True)
    start,end='2020-01-01','2026-08-01'
    market=load_market_data(args.raw_dir,start=start,end=end)
    market=market[market.index<pd.Timestamp(end,tz='UTC')]
    funding=load_funding(args.raw_dir,start=start,end=end)
    funding=funding[funding.index<pd.Timestamp(end,tz='UTC')]
    batches=list(iter_intrabar_months(args.raw_dir,start=start,end=end))
    expected=int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()/60)
    observed=sum(len(b) for b in batches)
    if observed != expected-55:
        raise ValueError(f'Unexpected data coverage: {observed}/{expected}; run prepare_v8_data and audit first')
    for previous,current in zip(batches,batches[1:]):
        if current.index[0] <= previous.index[-1]:
            raise ValueError('Overlapping minute archives would double-count execution')
    p=V8Params(**json.loads(Path(args.params).read_text()))
    v4p=V43Params(**json.loads(Path('configs/v4_1_2_params.json').read_text()))
    v4=generate_v43_signals(market,v4p)
    # The standalone baseline must use the same post-stop cycle lock as the
    # routed portfolio, otherwise its improvement is confounded with V8.
    v4side=np.sign(v4['signal'].fillna(0))
    v4cycles=(v4side.ne(0) & v4side.ne(v4side.shift(1,fill_value=0))).cumsum()
    v4['cycle_id']='direction_'+v4cycles.astype(str)
    v8=generate_v8_signals(market,p)
    enhanced=replace(p,target_vol=p.target_vol*1.5,max_leverage=3,risk_per_cycle=p.risk_per_cycle*1.5)
    single=replace(p,max_layers=1)
    config=MicroBacktestConfig(taker_fee_bps=2.4,maker_fee_bps=.12,maker_enabled=True,
                              maker_offset_bps=.5,conservative_protection=True)
    specs=[
        ('V8_base',p,v8,config),
        ('V8_single_same_initial',replace(p,max_layers=1,target_vol=p.target_vol/3,risk_per_cycle=p.risk_per_cycle/3),None,config),
        ('V8_single_same_budget',replace(p,max_layers=1),None,config),
        ('V8_leverage_1_5',replace(p,target_vol=p.target_vol*1.5,max_leverage=3,risk_per_cycle=p.risk_per_cycle*1.5),None,config),
        ('V8_maker_fee_1_2bps',p,v8,replace(config,maker_fee_bps=1.2)),
        ('V8_taker_only',p,v8,replace(config,maker_enabled=False)),
        ('V4_1_2',v4p,v4,replace(config,maker_offset_bps=v4p.maker_offset_bps)),
        ('V4_1_2_plus_V8',p,route_v4_v8_signals(v4,v8),replace(config,maker_offset_bps=0.0)),
        ('V4_1_2_plus_V8_1_5',enhanced,route_v4_v8_signals(v4,generate_v8_signals(market,enhanced)),replace(config,maker_offset_bps=0.0)),
        ('V4_1_2_plus_V8_single',single,route_v4_v8_signals(v4,generate_v8_signals(market,single)),replace(config,maker_offset_bps=0.0)),
    ]
    rows=[];details={};equities={}
    if args.only:
        available={s[0] for s in specs}
        if set(args.only)-available: raise ValueError('Unknown comparison case')
        specs=[s for s in specs if s[0] in args.only]
        if (output/'report.json').exists():
            details=json.loads((output/'report.json').read_text())['strategies']
            details={k:v for k,v in details.items() if k not in args.only}
            rows=[v['metrics'] for v in details.values()]
            old=pd.read_csv(output/'equity_comparison.csv',index_col=0,parse_dates=True)
            equities={c:old[c] for c in old if c not in args.only}
    for label,params,signals,execution in specs:
        signals=generate_v8_signals(market,params) if signals is None else signals
        result=run_micro_backtest(signals,batches,funding,execution)
        write_micro_report(result,params,execution,output/label)
        periods=micro_period_metrics(result)
        row={'strategy':label,**result.metrics,**frequency(result.trades,start,end)}
        for name,met in periods.items():
            if name.startswith('full'):continue
            for key in ('total_return','max_drawdown','sharpe','trade_count'):
                row[name+'_'+key]=met[key]
        rows.append(row)
        details[label]={'metrics':row,'parameters':params.to_dict(),'execution':asdict(execution)}
        if 'plus_V8' in label:details[label]['direction_parameters']=v4p.to_dict()
        equities[label]=result.equity
        pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
        print(json.dumps({'strategy':label,'return':row['total_return'],'drawdown':row['max_drawdown'],
                          'trades':row['trade_count'],'max_gap_days':row['max_days_between_entries']}),flush=True)
    expected=int((pd.Timestamp(end)-pd.Timestamp(start)).total_seconds()/60)
    observed=sum(len(b) for b in batches)
    report={'data':{'start_inclusive_utc':start,'end_exclusive_utc':end,'signal_interval':'4h','execution_interval':'1m',
                     'expected_minutes':expected,'observed_minutes':observed,'coverage':observed/expected,
                     'source_directory':args.raw_dir},
            'fee_assumption':{'base_taker_bps':4.,'base_maker_bps':.2,'rebate':.4,
                              'effective_taker_bps':2.4,'effective_maker_bps':.12,'rebate_settlement':'immediate net cost proxy'},
            'validation_note':'Development ranking uses 2020-2024; 2025+ was inspected in earlier exploratory research and is not a pristine blind test.',
            'limitations':['55 missing mark-price minutes remain in official daily archives; no fabricated prices.',
                           'Maker touch proxy omits queues and latency. Taker and higher-maker-cost controls included.',
                           'Equity/drawdown sampled every 4h, margin and liquidation checked at available 1m bars.',
                           'Stops can gap; conservative protective fills include adverse gap opens and impact.',
                           'V4+V8 uses one net position with V4 priority, no separate capital multiplication. Combined quotes use zero maker offset for both sleeves.',
                           'No V7.1 combined result is claimed; current checkout does not contain V7.1 execution engine.'],
            'strategies':details}
    (output/'report.json').write_text(json.dumps(report,indent=2))
    pd.DataFrame(equities).to_csv(output/'equity_comparison.csv')

if __name__=='__main__':main()
