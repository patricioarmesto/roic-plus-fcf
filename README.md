# ROIC + FCF Stock Screener

A powerful, hybrid stock screening tool designed to identify high-quality companies at reasonable valuations. It combines Quality Investing principles (ROIC, Growth) with a Dynamic Valuation model (PEG for growth stocks, FCF Yield for value stocks).

---

## 🚀 Key Features

- **Hybrid Valuation Model**: Automatically switches between **PEG Ratio** (for stocks with >15% CAGR) and **FCF Yield** (for value/mature stocks).
- **Quality First**: Screens for high **ROIC (Return on Invested Capital)** to ensure capital efficiency.
- **Financial Health**: Integrated **Debt/EBITDA** checks to avoid over-leveraged companies.
- **Smart Signals**: Clear **BUY / SELL / NEUTRAL** signals based on weighted scores.
- **Dual Data Sources**: Leverages **Financial Modeling Prep (FMP) API** for reliable metrics and **Yahoo Finance** for real-time fallback and supplementary data.
- **Parallel Processing**: Multi-threaded screening for fast performance across large ticker lists.

---

## 🛠️ Installation

This project uses [uv](https://github.com/astral-sh/uv) for lightning-fast dependency management.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/patricioarmesto/roic-plus-fcf.git
   cd roic-plus-fcf
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

---

## ⚙️ Configuration

Create a `.env` file in the root directory to store your API keys:

```env
FMP_API_KEY=your_api_key_here
```

> [!TIP]
> You can get a free API key from [Financial Modeling Prep](https://financialmodelingprep.com/developer/docs/). While optional (the tool has fallback logic), it is highly recommended for more accurate TTM metrics.

---

## 📖 Usage

Run the screener by providing an input file (TXT or CSV) containing stock tickers.

### Basic Command
```bash
uv run main.py --input tickers.txt
```

### Advanced Filtering
You can filter the output by **Valuation** or **Signal**:

```bash
# Only see 'Buy' signals for 'Cheap' or 'Reasonable' stocks
uv run main.py --input tickers.txt --signal buy --valuation cheap,reasonable
```

### CLI Arguments
| Argument | Shortcut | Description |
| :--- | :--- | :--- |
| `--input` | - | Path to `.txt` (one per line) or `.csv` (with a 'ticker' column). |
| `--workers` | - | Number of parallel threads (default: 4). |
| `--valuation` | `-v` | Filter: `cheap`, `reasonable`, `expensive`, `very_expensive`, `extreme`, `unknown`. |
| `--signal` | `-s` | Filter: `buy`, `neutral`, `sell`, `high_leverage`, `excluded_sector`, `error`. |

---

## 📊 Methodology

The tool calculates a **Final Score (0-100)** based on three pillars:

### 1. Quality & Growth (Weighted 65% + 20% Growth)
- **ROIC (45% weight)**: Target is **25%+**. We prefer companies that generate high returns on their capital.
- **FCF Yield (35% weight)**: Target is **10%+**. Real cash generation is prioritized over accounting earnings.
- **Revenue CAGR (20% weight)**: Target is **18%+**. Consistent top-line growth is essential for compounding.

### 2. Dynamic Valuation (The Penalty System)
Instead of a fixed target, the score is penalized or boosted based on current price relative to growth:
- **Growth Stocks (>15% CAGR)**: Evaluated via **PEG Ratio**.
    - PEG < 1.0: `Cheap` (10% Bonus)
    - PEG > 2.5: `Extreme` (40% Penalty)
- **Value Stocks (<15% CAGR)**: Evaluated via **FCF Yield**.
    - Yield > 8%: `Cheap`
    - Yield < 1%: `Extreme`

### 3. Safety Buffers
- **Debt/EBITDA**: If > 3.5x, the signal is automatically set to **HIGH_LEVERAGE**.
- **Buy Block**: Even if the score is high, a **BUY** signal is blocked if Debt/EBITDA > 2.5x.
- **Excluded Sectors**: Banks and Insurance companies are excluded by default as traditional ROIC/Debt metrics don't apply to them.

---

## 📄 Output
The tool displays a formatted table in the terminal and saves a detailed CSV report to `screen_results_v23_growth.csv`.

---

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/patricioarmesto/roic-plus-fcf/issues).

---

*Disclaimer: This tool is for informational purposes only. It does not constitute financial advice.*