import numpy as np
import pandas as pd
import pytest
from btc_regime.v8 import V8Params, generate_v8_signals, route_v4_v8_signals
from btc_regime.micro_backtest import MicroBacktestConfig, run_micro_backtest
from test_range_grid import synthetic_market, range_params


def test_v8_fixed_stop_and_basket_risk_are_causal():
    market = synthetic_market(100 + 5 * np.sin(np.linspace(0, 40*np.pi, 900)))
    params = V8Params(**(range_params().to_dict() | {
        'fixed_entry_risk': True, 'risk_per_cycle': .0075,
        'symmetric_vol_shock': True, 'trend_guard_return': 1.0,
    }))
    signals = generate_v8_signals(market, params)
    changed = market.copy()
    changed.loc[changed.index[500]:, ['open','high','low','close']] *= 1.5
    future_changed = generate_v8_signals(changed, params)
    pd.testing.assert_frame_equal(signals.iloc[:500], future_changed.iloc[:500])
    active = signals[signals.signal != 0]
    assert len(active) > 0
    loss = active.signal.abs() * (active.entry_price-active.stop_price).abs()/active.entry_price
    assert (loss <= params.risk_per_cycle+1e-12).all()
    cycles = signals.rg_entry_event.cumsum()
    for _, rows in signals[signals.signal != 0].groupby(cycles):
        assert rows.stop_price.nunique() == 1


def test_route_keeps_direction_priority_and_matching_protection():
    index = pd.date_range('2024-01-01', periods=3, freq='4h', tz='UTC')
    a = pd.DataFrame({'signal':[2.,0.,0.], 'regime':['trend']*3,
                      'stop_price':[90.,np.nan,np.nan], 'take_profit_price':[120.,np.nan,np.nan]},index=index)
    b = pd.DataFrame({'signal':[-1.,-1.,0.], 'regime':['range']*3,
                      'cycle_id':['v8_1','v8_1','v8_1'], 'rg_entry_event':[True,False,False],
                      'stop_price':[105.,105.,np.nan], 'take_profit_price':[95.,95.,np.nan]},index=index)
    routed = route_v4_v8_signals(a,b,v8_allocation=.5)
    assert routed.signal.tolist() == [2.,-.5,0.]
    assert routed.stop_price.iloc[:2].tolist() == [90.,105.]
    assert np.isnan(routed.stop_price.iloc[2])
    with pytest.raises(ValueError):route_v4_v8_signals(a,b,v8_allocation=1.1)
    with pytest.raises(ValueError):route_v4_v8_signals(a,b.iloc[:2])


def test_fresh_v8_routing_does_not_resume_stale_inventory_after_direction():
    index = pd.date_range('2024-01-01', periods=4, freq='4h', tz='UTC')
    direction = pd.DataFrame({'signal':[2.,2.,0.,0.], 'regime':['trend']*4}, index=index)
    v8 = pd.DataFrame({'signal':[1.,1.,1.,1.], 'regime':['range']*4,
                       'cycle_id':['v8_1']*4, 'rg_entry_event':[True,False,False,True],
                       'stop_price':[90.]*4, 'take_profit_price':[110.]*4}, index=index)
    routed = route_v4_v8_signals(direction, v8, require_fresh_v8_entry=True)
    assert routed.signal.tolist() == [2., 2., 0., 1.]


def test_protection_fills_stop_gap_at_adverse_open_and_counts_all_fills():
    signaled = pd.DataFrame({'signal':[1.], 'stop_price':[95.], 'take_profit_price':[120.]},
                           index=pd.DatetimeIndex(['2024-01-01T00:00Z']))
    idx=pd.DatetimeIndex(['2024-01-01T04:00Z','2024-01-01T04:01Z'])
    minute=pd.DataFrame(index=idx)
    for prefix in ('trade','mark'):
        for key, values in {'open':[100.,90.],'high':[101.,91.],'low':[99.,89.],'close':[100.,90.]}.items():
            minute[prefix+'_'+key]=values
    minute['trade_volume']=1e6;minute['trade_quote_volume']=1e8
    funding=pd.DataFrame({'funding_rate':[]},index=pd.DatetimeIndex([],tz='UTC'))
    r=run_micro_backtest(signaled,[minute],funding,MicroBacktestConfig(conservative_protection=True))
    stop=r.fills[r.fills.reason=='stop_loss']
    assert len(stop)==1
    assert stop.iloc[0].price < 90.
    assert r.metrics['maker_fill_count']+r.metrics['taker_fill_count']==len(r.fills)
    assert r.metrics['order_notional']==pytest.approx(r.fills.notional.sum())


def test_stopped_v8_cycle_cannot_reopen_on_a_size_update():
    idx=pd.DatetimeIndex(['2024-01-01T00:00Z','2024-01-01T04:00Z'])
    signals=pd.DataFrame({'signal':[1.,1.5],'stop_price':[95.,95.],
                          'take_profit_price':[120.,120.],'cycle_id':['v8_1','v8_1']},index=idx)
    midx=pd.DatetimeIndex(['2024-01-01T04:00Z','2024-01-01T04:01Z','2024-01-01T08:00Z'])
    minute=pd.DataFrame(index=midx)
    for prefix in ('trade','mark'):
        for key,values in {'open':[100.,90.,100.],'high':[101.,91.,101.],
                           'low':[99.,89.,99.],'close':[100.,90.,100.]}.items():
            minute[prefix+'_'+key]=values
    minute['trade_volume']=1e6;minute['trade_quote_volume']=1e8
    funding=pd.DataFrame({'funding_rate':[]},index=pd.DatetimeIndex([],tz='UTC'))
    r=run_micro_backtest(signals,[minute],funding,MicroBacktestConfig(conservative_protection=True))
    assert (r.fills.reason=='signal').sum()==1
    assert (r.fills.reason=='stop_loss').sum()==1
