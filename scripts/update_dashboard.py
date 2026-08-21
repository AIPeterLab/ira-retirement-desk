#!/usr/bin/env python3
from __future__ import annotations
import json,os,time
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]; MODE="ira"; START=date(2026,8,3)
SYMBOLS=["QQQ","QLD","SPY","SSO","CHAT","QTUM","BTC-USD"]
QQQ_SIGNALS_URL=os.environ.get("QQQ_SIGNALS_URL","https://raw.githubusercontent.com/AIPeterLab/qqq-qld-signal-desk/main/data/signals.json")
SPY_SIGNALS_URL=os.environ.get("SPY_SIGNALS_URL","https://raw.githubusercontent.com/AIPeterLab/spy-sso-signal-desk/main/data/signals.json")
MAX_SIGNAL_AGE_HOURS=int(os.environ.get("MAX_QQQ_SIGNAL_AGE_HOURS","96"))
HALVING=date(2024,4,20); BTC_BUY=HALVING-timedelta(days=500); BTC_SELL=HALVING+timedelta(days=540)
IRA_START_VALUES={"IRA_QQQ":4880.0,"IRA_SPY":4880.0,"IRA_BTC":2550.0,"IRA_CASH":2300.0}

def fetch(symbol):
    end=int(time.time())+86400; start=int(datetime(2005,1,1,tzinfo=timezone.utc).timestamp())
    u=f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol,safe='')}?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
    with urlopen(Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=40) as r:p=json.load(r)["chart"]["result"][0]
    a=p["indicators"]["adjclose"][0]["adjclose"]
    return {datetime.fromtimestamp(t,timezone.utc).date():float(v) for t,v in zip(p["timestamp"],a) if v is not None}

def aligned(series):
    days=sorted(set.intersection(*(set(x) for x in series.values())))
    return days

def fetch_qqq_signals():
    with urlopen(Request(QQQ_SIGNALS_URL,headers={"User-Agent":"AIPeterLab-retirement-dashboard"}),timeout=40) as r: source=json.load(r)
    generated=datetime.fromisoformat(source["generated_at_utc"].replace("Z","+00:00"))
    age=(datetime.now(timezone.utc)-generated.astimezone(timezone.utc)).total_seconds()/3600
    if age<0 or age>MAX_SIGNAL_AGE_HOURS:raise RuntimeError(f"QQQ Signal Desk source is stale ({age:.1f} hours old)")
    current=source.get("current",{}); state=current.get("model_state"); signal=current.get("donchian_signal")
    if state not in {"QLD","QQQ","Cash"} or signal not in {0,1}:raise RuntimeError("QQQ Signal Desk source has an invalid current signal")
    history={date.fromisoformat(row["date"]):(row["model_state"],row["donchian_signal"],row.get("qqq_ema200"),row.get("qld_prior_20d_high"),row.get("qld_prior_20d_low")) for row in source.get("recent_history",[]) if row.get("model_state") in {"QLD","QQQ","Cash"}}
    history[date.fromisoformat(source["last_updated"])]=(state,signal,source.get("market",{}).get("qqq_ema200"),source.get("market",{}).get("qld_prior_20d_high"),source.get("market",{}).get("qld_prior_20d_low"))
    return source,history

def fetch_spy_signals():
    with urlopen(Request(SPY_SIGNALS_URL,headers={"User-Agent":"AIPeterLab-retirement-dashboard"}),timeout=40) as r: source=json.load(r)
    generated=datetime.fromisoformat(source["generated_at_utc"].replace("Z","+00:00"))
    age=(datetime.now(timezone.utc)-generated.astimezone(timezone.utc)).total_seconds()/3600
    if age<0 or age>MAX_SIGNAL_AGE_HOURS:raise RuntimeError(f"SPY Signal Desk source is stale ({age:.1f} hours old)")
    summary=source.get("summary",{}); valid={"SSO","50% SSO / 50% SPY","Cash"}
    if summary.get("position") not in valid:raise RuntimeError("SPY Signal Desk source has an invalid current position")
    history={date.fromisoformat(row["date"]):(row["position"],row.get("sma200"),row.get("target_spy_pct",0),row.get("target_sso_pct",0),row.get("target_cash_pct",0)) for row in source.get("daily",[]) if row.get("position") in valid}
    if not history:raise RuntimeError("SPY Signal Desk source has no authoritative daily history")
    return source,history

def latest_on_or_before(mapping,d):
    k=max(x for x in mapping if x<=d); return mapping[k]

def simulate_roth(px,qs):
    days=[d for d in aligned({k:px[k] for k in ["QQQ","QLD","SPY","CHAT","QTUM","BTC-USD"]}) if d>=date(2023,5,18)]
    values={"QQQ / QLD":3000.0,"CHAT":2500.0,"QTUM":2500.0,"BTC / Cash":2000.0}; prev=days[0]
    b1=10000.0;b2=10000.0
    for d in days[1:]:
        oldpos=qs[prev][0]; values["QQQ / QLD"]*=px[oldpos][d]/px[oldpos][prev] if oldpos!="Cash" else 1
        values["CHAT"]*=px["CHAT"][d]/px["CHAT"][prev]; values["QTUM"]*=px["QTUM"][d]/px["QTUM"][prev]
        if BTC_BUY<=prev<=BTC_SELL:values["BTC / Cash"]*=px["BTC-USD"][d]/px["BTC-USD"][prev]
        b1*=.5*px["QQQ"][d]/px["QQQ"][prev]+.5*px["SPY"][d]/px["SPY"][prev]
        b2*=sum(.2*px[s][d]/px[s][prev] for s in ["QQQ","SPY","BTC-USD","CHAT","QTUM"])
        prev=d
    return values,b1,b2,days[-1]

def simulate_ira(px,qs,ss):
    days=[d for d in aligned({k:px[k] for k in ["QQQ","QLD","SPY","SSO","BTC-USD"]}) if d>=START]
    if not days:
        raise RuntimeError(f"No common market data is available on or after {START}")
    values=IRA_START_VALUES.copy(); prev=days[0]
    for d in days[1:]:
        qpos=qs[prev][0]
        _,_,spy_weight,sso_weight,_=latest_on_or_before(ss,prev)
        if qpos!="Cash":values["IRA_QQQ"]*=px[qpos][d]/px[qpos][prev]
        values["IRA_SPY"]*=spy_weight*px["SPY"][d]/px["SPY"][prev]+sso_weight*px["SSO"][d]/px["SSO"][prev]+(1-spy_weight-sso_weight)
        if BTC_BUY<=prev<=BTC_SELL:values["IRA_BTC"]*=px["BTC-USD"][d]/px["BTC-USD"][prev]
        prev=d
    return values,days[-1]

def status_action(weight,target,lo,hi):return "Rebalance toward target" if weight<lo or weight>hi else "No action"
def add_holding_fields(sleeve,px,market):
    position=sleeve["position"]
    symbol="BTC-USD" if position=="BTC" else position
    price=1.0 if position=="Cash" else latest_on_or_before(px[symbol],market)
    sleeve.update({"price":round(price,2),"shares":round(sleeve["value"]/price,4)})
    return sleeve
def assert_qqq_consistency(payload,source):
    expected_state=source["current"]["model_state"]; expected_note=f"Donchian signal {source['current']['donchian_signal']}"
    sleeve=next((x for x in payload["sleeves"] if x["name"]=="IRA_QQQ"),None)
    metric=next((x for x in payload["metrics"] if x["label"]=="QQQ strategy"),None)
    if not sleeve or sleeve.get("position")!=expected_state or not metric or metric.get("value")!=f"Hold {expected_state}" or metric.get("note")!=expected_note:
        raise RuntimeError("IRA QQQ output differs from QQQ Signal Desk")
def assert_spy_consistency(payload,source):
    expected=source["summary"]["position"]
    sleeve=next((x for x in payload["sleeves"] if x["name"]=="IRA_SPY"),None)
    metric=next((x for x in payload["metrics"] if x["label"]=="SPY strategy"),None)
    if not sleeve or sleeve.get("position")!=expected or not metric or metric.get("value")!=f"Hold {expected}":raise RuntimeError("IRA SPY output differs from SPY Signal Desk")
def write():
    qqq_source,qs=fetch_qqq_signals(); spy_source,ss=fetch_spy_signals(); px={s:fetch(s) for s in SYMBOLS}
    market=max(d for d in set(px["QQQ"])&set(px["SPY"])); qpos=qqq_source["current"]["model_state"]; qsig=qqq_source["current"]["donchian_signal"]; spos=spy_source["summary"]["position"]; ssma=spy_source["summary"]["sma200"]
    btc_day=max(px["BTC-USD"]); bpos="BTC" if BTC_BUY<=btc_day<=BTC_SELL else "Cash"; cycle=(btc_day-HALVING).days
    if MODE=="roth":
        vals,b1,b2,market=simulate_roth(px,qs); total=sum(vals.values()); specs=[("QQQ / QLD",30,25,35,qpos,"Risk-on" if qpos=="QLD" else "Defensive"),("CHAT",25,20,30,"CHAT","Hold"),("QTUM",25,20,30,"QTUM","Hold"),("BTC / Cash",20,15,25,bpos,"Risk-on" if bpos=="BTC" else "Risk-off")]
        sleeves=[]
        for n,t,lo,hi,p,s in specs:
            w=vals[n]/total*100;sleeves.append({"name":n,"value":round(vals[n],2),"weight":w,"target":t,"drift":w-t,"position":p,"signal":s,"action":status_action(w,t,lo,hi),"note":"Annual thesis review" if n in ["CHAT","QTUM"] else "Strategy signal controls position"})
        active=total; benchmarks=[{"name":"Active Roth model","value":active,"return_pct":active/10000*100-100,"diff":0,"rule":"30/25/25/20 active rules"},{"name":"Benchmark 1","value":b1,"return_pct":b1/10000*100-100,"diff":b1-active,"rule":"QQQ 50% / SPY 50%"},{"name":"Benchmark 2","value":b2,"return_pct":b2/10000*100-100,"diff":b2-active,"rule":"QQQ/SPY/BTC/CHAT/QTUM 20% each"}]
        outside=[x for x in sleeves if x["action"]!="No action"]; action="Annual rebalance review" if outside else "No action"
        payload={"mark":"R","title":"Roth Estate-Growth Desk","subtitle":"Aggressive long-horizon portfolio · strategy rules before rebalancing","lead_label":"Normalized model value","total_value":active,"required_action":action,"next_review":"May 2027","explanation":"Daily model tracking from a normalized $10,000 start on CHAT's first trading date. Private brokerage balances are not published.","allocation_label":"Active 30/25/25/20 model","tracking_start":"2023-05-18","sleeves":sleeves,"benchmarks":benchmarks,"rules":[{"title":"Signals decide position","copy":"QLD/QQQ/Cash and BTC/Cash change only under their written models."},{"title":"Themes stay invested","copy":"CHAT and QTUM are buy-and-hold sleeves with annual thesis review."},{"title":"Bands decide size","copy":"Rebalance annually only when a sleeve is outside its stated band."},{"title":"Drawdown is not a sell rule","copy":"A valid strategy exit or thesis failure is required."}],"metrics":[{"label":"QQQ strategy","value":f"Hold {qpos}","note":f"Donchian signal {qsig}"},{"label":"BTC strategy","value":f"Hold {bpos}","note":f"Cycle day {cycle}"},{"label":"CHAT close","value":f"${px['CHAT'][market]:,.2f}","note":"Buy and hold"},{"label":"QTUM close","value":f"${px['QTUM'][market]:,.2f}","note":"Buy and hold"},{"label":"Benchmark 1","value":f"${b1:,.0f}","note":"50/50 QQQ/SPY"},{"label":"Benchmark 2","value":f"${b2:,.0f}","note":"Five-way equal weight"}]}
    else:
        base,market=simulate_ira(px,qs,ss); base={k:round(v,2) for k,v in base.items()}; start_total=sum(IRA_START_VALUES.values()); total=sum(base.values()); growth=sum(base[k] for k in ["IRA_QQQ","IRA_SPY","IRA_BTC"]); specs=[("IRA_QQQ",40,35,45,qpos,"Risk-on" if qpos=="QLD" else "Defensive"),("IRA_SPY",40,35,45,spos,"Risk-off" if spos=="Cash" else "Risk-on"),("IRA_BTC",20,15,25,bpos,"Risk-on" if bpos=="BTC" else "Risk-off")]; sleeves=[]
        for n,t,lo,hi,p,s in specs:
            w=base[n]/growth*100;sleeves.append({"name":n,"value":round(base[n],2),"weight":w,"target":t,"drift":w-t,"position":p,"signal":s,"action":status_action(w,t,lo,hi),"note":"Growth sleeve weight"})
        cash_target=IRA_START_VALUES["IRA_CASH"]/start_total*100; cash_weight=base["IRA_CASH"]/total*100
        sleeves.append({"name":"IRA_CASH","value":round(base["IRA_CASH"],2),"weight":cash_weight,"target":cash_target,"drift":cash_weight-cash_target,"position":"Cash","signal":"Reserve","action":"Confirm 3-year coverage","note":"Excluded from 40/40/20 target"}); outside=[x for x in sleeves[:3] if x["action"]!="No action"]
        qqq_start=latest_on_or_before(px["QQQ"],START); spy_start=latest_on_or_before(px["SPY"],START)
        qqq_benchmark=start_total*.5*px["QQQ"][market]/qqq_start; spy_benchmark=start_total*.5*px["SPY"][market]/spy_start
        benchmark_value=qqq_benchmark+spy_benchmark; benchmark_return=benchmark_value/start_total*100-100; active_return=total/start_total*100-100
        payload={"mark":"IRA","title":"IRA Reserve & Growth Desk","subtitle":"3-year cash reserve plus 40/40/20 growth sleeve","lead_label":"Live guide account value","total_value":total,"required_action":"Confirm reserve; "+("rebalance review" if outside else "no growth rebalance"),"next_review":"August 2027","explanation":"Estimated live values apply daily strategy returns to the August 3 guide balances. The cash reserve stays fixed; private broker balances are not fetched.","allocation_label":"Growth target 40/40/20","tracking_start":"2026-08-03","sleeves":sleeves,"benchmarks":[{"name":"Active IRA model","value":total,"return_pct":active_return,"diff":0,"rule":"Strategy-aware growth sleeves plus fixed cash reserve"},{"name":"QQQ / SPY 50/50 benchmark","value":benchmark_value,"return_pct":benchmark_return,"diff":benchmark_value-total,"rule":"$7,305 QQQ + $7,305 SPY at start; buy and hold"}],"rules":[{"title":"Check reserve first","copy":"Confirm IRA_CASH covers the intended three-year withdrawal need."},{"title":"Apply strategy signals","copy":"QQQ, SPY, and BTC sleeve positions follow their source models."},{"title":"Calculate growth-only weights","copy":"Use IRA_QQQ, IRA_SPY, and IRA_BTC for the 40/40/20 test."},{"title":"Defensive signal wins","copy":"Never override an exit merely because a sleeve is below target."}],"metrics":[{"label":"Cash reserve","value":f"${base['IRA_CASH']:,.0f}","note":"3-year protection bucket"},{"label":"50/50 benchmark","value":f"${benchmark_value:,.0f}","note":f"QQQ ${qqq_benchmark:,.0f} · SPY ${spy_benchmark:,.0f}"},{"label":"QQQ strategy","value":f"Hold {qpos}","note":f"Donchian signal {qsig}"},{"label":"SPY strategy","value":f"Hold {spos}","note":f"SPY ${px['SPY'][market]:.2f} · SMA200 ${ssma:.2f}"},{"label":"BTC strategy","value":f"Hold {bpos}","note":f"Cycle day {cycle}"},{"label":"Annual band test","value":"In band" if not outside else "Review","note":"QQQ 35–45 · SPY 35–45 · BTC 15–25"}]}
    assert_qqq_consistency(payload,qqq_source)
    assert_spy_consistency(payload,spy_source)
    payload.update({"market_date":str(market),"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"qqq_signal_source":{"repository":"AIPeterLab/qqq-qld-signal-desk","source_market_date":qqq_source["last_updated"],"source_generated_at":qqq_source["generated_at_utc"],"model_state":qpos,"donchian_signal":qsig},"spy_signal_source":{"repository":"AIPeterLab/spy-sso-signal-desk","source_market_date":spy_source["last_updated"],"source_generated_at":spy_source["generated_at_utc"],"position":spos,"trend_state":spy_source["summary"]["trend_state"],"sma200":ssma},"footer":"Daily market and strategy refresh at 5:00 PM New York time. Private broker balances are not fetched. This is an operating display, not tax, legal, or individualized financial advice."})
    payload["sleeves"]=[add_holding_fields(x,px,market) for x in payload["sleeves"]]
    (ROOT/"data").mkdir(exist_ok=True);(ROOT/"data"/"dashboard.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":write()
