# roic-plus-fcf — agent guide

## Project structure

Single-file app: everything in `main.py`. No modules, no tests, no CI, no lint/typecheck config.

## Commands

```sh
uv sync                    # install deps (uv, not pip/poetry)
uv run main.py --input tickers.txt
uv run main.py --input tickers.txt --signal buy --valuation cheap,reasonable
```

## Input files

- `.txt`: one ticker per line, `#` comments allowed
- `.csv`: needs a `ticker` or `symbol` column

## Key constants (hardcoded in `main.py`)

| Constant | Value | Effect |
|---|---|---|
| `ROIC_GOOD` | 25% | Target for scoring |
| `FCF_YIELD_GOOD` | 10% | Target for scoring |
| `REV_CAGR_GOOD` | 18% | Target for scoring |
| `GROWTH_THRESHOLD` | 15% CAGR | Above = PEG valuation; below = FCF yield valuation |
| `BUY_LEVEL` | 80 | Score ≥ 80 → buy |
| `SELL_LEVEL` | 40 | Score ≤ 40 → sell |
| `MAX_DEBT_EBITDA` | 3.5 | Forces `high_leverage` signal |
| `BUY_MAX_DEBT` | 2.5 | Blocks buy signal (downgrades to neutral) |
| `EXCLUDED_SECTORS` | `{"banks","insurance","bank"}` | Marked `excluded_sector`, not analyzed |

## Scoring (line 243)

Weighted: ROIC × 45% + FCF Yield × 35% + CAGR × 20%, then × valuation penalty (cheap=1.1, reasonable=1.0, expensive=0.9, very_expensive=0.75, extreme=0.6, unknown=0.85).

## Data sources

- **FMP API** (`FMP_API_KEY` in `.env`): primary source for ROIC TTM, FCF Yield TTM, Debt/EBITDA TTM, Forward PE — fetched via `financialmodelingprep.com/stable/key-metrics-ttm`
- **yfinance**: fallback for all metrics; primary for sector, price, market cap, CAGR

FMP is optional — falls back to yfinance-calculated values if unavailable or rate-limited.

## Quirks

- 120ms `time.sleep(0.12)` between ticker fetches to avoid rate limits
- Output CSV always overwrites `screen_results_v23_growth.csv` in CWD
- `.env` is gitignored (secrets); `*.csv` is gitignored (output)
- `--workers` default is 4 (argparse) but `run_screen()` internally defaults to 6 — the argparse value wins at runtime
- ROIC is clamped to [-50%, 250%]; CAGR to [-50%, 100%]; FCF Yield to [-20%, 20%]
- If invested capital ≤ 0 but NOPAT > 0, ROIC returns 250% (buyback-heavy companies)
- No pre-filtering: every ticker in the input is fetched. Banks/insurance get `excluded_sector` signal but are still processed.
