# =========================================================
# screen_stocks_v2_3_growth.py - valuation híbrida FCF + PEG
# =========================================================
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, List
import os, re, time
from functools import lru_cache

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()
FMP_API_KEY: Optional[str] = os.getenv("FMP_API_KEY")

# CONFIG
ROIC_GOOD = 25.0
FCF_YIELD_GOOD = 10.0
REV_CAGR_GOOD = 18.0
BUY_LEVEL = 80
SELL_LEVEL = 40
MAX_DEBT_EBITDA = 3.5
BUY_MAX_DEBT = 2.5
EXCLUDED_SECTORS = {"banks","insurance","bank"}
GROWTH_THRESHOLD = 15.0  # >15% CAGR usa PEG

def safe_float(x):
    try:
        if x is None: return None
        v = float(x)
        return None if np.isnan(v) else v
    except: return None

def clamp(x, lo, hi): return max(lo, min(x, hi))
def normalize_name(x): return re.sub(r"\s+", " ", str(x).lower().replace("-"," ").replace("_"," ").replace("&","and")).strip()
def normalize_sector(s): return "unknown" if s is None else re.sub(r"\s+", " ", str(s).lower().replace("-"," ").replace("_"," ")).strip()
def fmt_pct(x): return "-" if x is None or pd.isna(x) else f"{x:.1f}%"
def fmt_price(x): return "-" if x is None or pd.isna(x) else f"${x:.2f}"
def fmt_mcap(x):
    if x is None or pd.isna(x): return "-"
    if abs(x)>=1e12: return f"{x/1e12:.2f}T"
    if abs(x)>=1e9: return f"{x/1e9:.2f}B"
    if abs(x)>=1e6: return f"{x/1e6:.2f}M"
    return str(int(x))

def load_tickers(path: str) -> List[str]:
    p = Path(path)
    if not p.exists(): raise FileNotFoundError(path)
    if p.suffix.lower()==".csv":
        df = pd.read_csv(p)
        col = next((c for c in df.columns if c.lower() in ["ticker","tickers","symbol","symbols"]), None)
        if not col: raise ValueError("Ticker column not found")
        return df[col].astype(str).str.strip().dropna().drop_duplicates().tolist()
    return list(dict.fromkeys([l.strip() for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]))

def find_first_in_df(df, candidates):
    if df is None or df.empty: return None
    norm = {normalize_name(i): i for i in df.index}
    for c in candidates:
        key = normalize_name(c)
        if key in norm:
            s = df.loc[norm[key]].dropna()
            if len(s)>0:
                v = safe_float(s.iloc[0])
                if v is not None: return v
    return None

@lru_cache(maxsize=2000)
def fetch_fmp_metrics(symbol):
    empty = {"roic_pct":None,"fcf_yield_pct":None,"debt_to_ebitda":None,"pe_forward":None}
    if not FMP_API_KEY: return empty
    try:
        r = requests.get("https://financialmodelingprep.com/stable/key-metrics-ttm",
                         params={"symbol":symbol,"apikey":FMP_API_KEY}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data,list) or not data: return empty
        d = data[0]
        roic_raw = safe_float(d.get("returnOnInvestedCapitalTTM"))
        fcf_raw = safe_float(d.get("freeCashFlowYieldTTM"))
        debt_raw = safe_float(d.get("debtToEbitdaTTM"))
        pe_fwd = safe_float(d.get("peForwardTTM")) or safe_float(d.get("forwardPE"))
        return {
            "roic_pct": roic_raw * 100 if roic_raw is not None else None,
            "fcf_yield_pct": fcf_raw * 100 if fcf_raw is not None else None,
            "debt_to_ebitda": debt_raw,
            "pe_forward": pe_fwd
        }
    except: return empty

def extract_balance_metrics(t):
    try: balance = t.balance_sheet
    except: balance = pd.DataFrame()
    if balance is None or balance.empty:
        try: balance = t.quarterly_balance_sheet
        except: balance = pd.DataFrame()
    if balance.empty: return {"cash":0,"debt":0,"equity":None}
    cash = find_first_in_df(balance, ["Cash And Cash Equivalents","Cash Cash Equivalents And Short Term Investments"]) or 0
    debt_s = find_first_in_df(balance, ["Short Long Term Debt","Short Term Debt","Current Debt"]) or 0
    debt_l = find_first_in_df(balance, ["Long Term Debt"]) or 0
    equity = find_first_in_df(balance, ["Total Stockholder Equity","Stockholders Equity","Total Equity"])
    return {"cash":cash,"debt":debt_s+debt_l,"equity":equity}

def compute_enterprise_value(mcap,debt,cash):
    if mcap is None: return None
    ev = mcap + (debt or 0) - (cash or 0)
    return ev if ev>0 else None

def compute_roic(t):
    try: income, balance = t.financials, t.balance_sheet
    except: return None
    if income is None or income.empty or balance is None or balance.empty: return None
    ebit = find_first_in_df(income, ["Operating Income","EBIT"])
    if ebit is None: return None
    pretax = find_first_in_df(income, ["Pretax Income","Income Before Tax"])
    taxes = find_first_in_df(income, ["Income Tax Expense","Tax Provision"])
    tax_rate = clamp(abs(taxes)/abs(pretax),0,0.5) if pretax and taxes and pretax!=0 else 0.21
    nopat = ebit*(1-tax_rate)
    m = extract_balance_metrics(t)
    if m["equity"] is None: return None
    invested = m["equity"] + m["debt"] - m["cash"]
    if invested<=0: return None
    return clamp(nopat/invested*100, -50, 50)

def compute_revenue_cagr(t):
    try: inc = t.financials
    except: return None
    if inc is None or inc.empty: return None
    row = next((i for i in inc.index if "revenue" in i.lower()), None)
    if not row: return None
    rev = inc.loc[row].dropna().astype(float).values
    if len(rev)<2 or rev[-1]<=0: return None
    cagr = ((rev[0]/rev[-1])**(1/(len(rev)-1))-1)*100
    return clamp(cagr, -50, 35)

def compute_fcf_yield(info, ev, t, fmp_fcf=None):
    if fmp_fcf is not None and abs(fmp_fcf)<=100: 
        return clamp(fmp_fcf,-20,20)
    ocf = safe_float(info.get("operatingCashflow"))
    capex = safe_float(info.get("capitalExpenditures"))
    fcf = None
    if ocf is not None and capex is not None:
        fcf = ocf + capex
    else:
        fcf = safe_float(info.get("freeCashflow"))
    if fcf is None and t is not None:
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                ocf2 = find_first_in_df(cf, ["Total Cash From Operating Activities","Operating Cash Flow"])
                cap2 = find_first_in_df(cf, ["Capital Expenditures"])
                if ocf2 is not None and cap2 is not None:
                    fcf = ocf2 + cap2
        except: pass
    if fcf is None or not ev or ev<=0: return None
    fy = fcf/ev*100
    return clamp(fy,-20,20) if abs(fy)<=100 else None

def classify_valuation_growth(fcf_yield, forward_pe, rev_cagr):
    # Método híbrido: growth usa PEG, value usa FCF
    if rev_cagr and rev_cagr > GROWTH_THRESHOLD:
        if not forward_pe or forward_pe <= 0:
            return "unknown"
        peg = forward_pe / rev_cagr
        if peg < 1.0: return "cheap"
        if peg < 1.5: return "reasonable"
        if peg < 2.5: return "expensive"
        return "extreme"
    else:
        if fcf_yield is None: return "unknown"
        if fcf_yield >= 8: return "cheap"
        if fcf_yield >= 5: return "reasonable"
        if fcf_yield >= 3: return "expensive"
        if fcf_yield >= 1: return "very_expensive"
        return "extreme"

def valuation_penalty(v): 
    # Penalties más suaves para growth
    return {"cheap":1.1,"reasonable":1.0,"expensive":0.9,"very_expensive":0.75,"extreme":0.6,"unknown":0.85}.get(v,0.85)

def score_linear(val,target): 
    if val is None: return None
    if val<=0: return 0
    return clamp(val/target*100, 0, 100)  # cap duro a 100

def compute_final_score(roic_s,fcf_s,grow_s,valuation):
    parts=[(s,w) for s,w in [(roic_s,0.45),(fcf_s,0.35),(grow_s,0.20)] if s is not None]
    if not parts: return None
    base=sum(s*w for s,w in parts)/sum(w for _,w in parts)
    return clamp(base*valuation_penalty(valuation),0,100)

def classify_signal(score):
    if score is None: return "neutral"
    if score>=BUY_LEVEL: return "compra"
    if score<=SELL_LEVEL: return "venta"
    return "neutral"

def build_rationale(roic, fcf_yield, rev_cagr, forward_pe, valuation, debt_to_ebitda, signal):
    parts = []
    is_growth = rev_cagr is not None and rev_cagr > GROWTH_THRESHOLD
    if is_growth:
        peg = forward_pe / rev_cagr if forward_pe and forward_pe > 0 and rev_cagr else None
        parts.append(f"Growth stock (RevCAGR {rev_cagr:.1f}% > {GROWTH_THRESHOLD}%)")
        if peg is not None:
            parts.append(f"PEG={peg:.2f} → {valuation}")
        elif forward_pe is None:
            parts.append("No forward PE available for PEG")
    else:
        if rev_cagr is not None:
            parts.append(f"Value stock (RevCAGR {rev_cagr:.1f}%)")
        else:
            parts.append("Value stock (no CAGR data)")
        if fcf_yield is not None:
            parts.append(f"FCF yield={fcf_yield:.1f}% → {valuation}")
        else:
            parts.append("No FCF yield data")
    if roic is not None:
        quality = "high" if roic >= ROIC_GOOD else ("mid" if roic >= 10 else "low")
        parts.append(f"ROIC={roic:.1f}% ({quality})")
    if signal == "high_leverage":
        parts.append(f"Flagged: Debt/EBITDA={debt_to_ebitda:.1f}x > {MAX_DEBT_EBITDA}x")
    elif signal == "neutral" and debt_to_ebitda is not None and debt_to_ebitda >= BUY_MAX_DEBT:
        parts.append(f"Buy blocked: Debt/EBITDA={debt_to_ebitda:.1f}x >= {BUY_MAX_DEBT}x")
    return "; ".join(parts) if parts else "Insufficient data"

def fetch_one(symbol):
    res={"ticker":symbol.upper()}
    try:
        t=yf.Ticker(symbol)
        try: info=t.info or {}
        except: info={}
        if not info:
            try:
                fi=t.fast_info
                info={"currentPrice":getattr(fi,"last_price",None),"marketCap":getattr(fi,"market_cap",None),"freeCashflow":None,"operatingCashflow":None,"capitalExpenditures":None,"ebitda":None,"forwardPE":None}
            except: info={}
        sector=normalize_sector(info.get("sector"))
        if sector in EXCLUDED_SECTORS:
            res.update({"sector":sector,"signal":"excluded_sector"}); return res
        price=safe_float(info.get("currentPrice")); mcap=safe_float(info.get("marketCap"))
        m=extract_balance_metrics(t); ev=compute_enterprise_value(mcap,m["debt"],m["cash"])
        fmp=fetch_fmp_metrics(symbol)
        roic=fmp["roic_pct"] if fmp["roic_pct"] is not None else compute_roic(t)
        fcf_y=compute_fcf_yield(info,ev,t,fmp["fcf_yield_pct"])
        rev_cagr=compute_revenue_cagr(t)
        forward_pe = safe_float(info.get("forwardPE")) or fmp["pe_forward"]
        val=classify_valuation_growth(fcf_y, forward_pe, rev_cagr)
        score=compute_final_score(score_linear(roic,ROIC_GOOD),score_linear(fcf_y,FCF_YIELD_GOOD),score_linear(rev_cagr,REV_CAGR_GOOD),val)
        signal=classify_signal(score)
        debt_ebitda=fmp["debt_to_ebitda"]
        if debt_ebitda is None:
            ebitda = safe_float(info.get("ebitda"))
            if ebitda and ebitda>0 and m["debt"]>0:
                debt_ebitda = m["debt"]/ebitda
        if signal=="compra" and (debt_ebitda is None or debt_ebitda >= BUY_MAX_DEBT):
            signal = "neutral"
        if debt_ebitda and debt_ebitda>MAX_DEBT_EBITDA:
            signal="high_leverage"
        rationale = build_rationale(roic, fcf_y, rev_cagr, forward_pe, val, debt_ebitda, signal)
        res.update({"sector":sector,"signal":signal,"score":score,"roic":roic,"fcf_yield":fcf_y,"rev_cagr":rev_cagr,"valuation":val,"debt_to_ebitda":debt_ebitda,"price":price,"market_cap":mcap,"forward_pe":forward_pe,"rationale":rationale})
    except Exception as e: res.update({"signal":"error","error":str(e)})
    time.sleep(0.12)
    return res

def run_screen(tickers, workers=6):
    rows=[]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(fetch_one,t):t for t in tickers}
        for f in as_completed(futs): rows.append(f.result())
    df=pd.DataFrame(rows)
    if "score" in df.columns: df=df.sort_values("score",ascending=False,na_position="last")
    return df.reset_index(drop=True)

def pretty_print(df):
    headers=["Ticker","Signal","Score","ROIC","FCFY","CAGR","Val","D/E","FwdPE"]
    rows=[]
    for _,r in df.iterrows():
        rows.append([
            r.get("ticker"),
            r.get("signal"),
            fmt_pct(r.get("score")),
            fmt_pct(r.get("roic")),
            fmt_pct(r.get("fcf_yield")),
            fmt_pct(r.get("rev_cagr")),
            r.get("valuation"),
            f"{r.get('debt_to_ebitda'):.1f}" if pd.notna(r.get('debt_to_ebitda')) else "-",
            f"{r.get('forward_pe'):.1f}" if pd.notna(r.get('forward_pe')) else "-",
        ])
    print(tabulate(rows,headers=headers,tablefmt="simple"))

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",required=True); p.add_argument("--workers",type=int,default=4); a=p.parse_args()
    tickers=load_tickers(a.input)
    df=run_screen(tickers,a.workers)
    pretty_print(df)
    df.to_csv("screen_results_v23_growth.csv",index=False)
    print("Guardado: screen_results_v23_growth.csv (método híbrido PEG+FCF)")

if __name__=="__main__": main()
