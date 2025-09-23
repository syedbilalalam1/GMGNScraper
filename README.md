# GMGN Scraper Suite
<img width="1919" height="1080" alt="Image" src="https://github.com/user-attachments/assets/ef877637-e83a-4bb1-bfec-c177e18f5dc7" />

## Overview
GMGN Scraper is a toolkit for scraping and extracting data from [gmgn.ai](https://gmgn.ai), a Solana-based trading analytics platform. It provides both Python and Node.js tools to collect wallet addresses, trading panels, recent PnL, and deployed token data for further analysis or automation.

---

## Features
- **Scrape Solana wallet addresses** from GMGN trade pages
- **Extract trading panel data** (Recent PnL, Deployed Tokens, etc.)
- **Save results to CSV and JSON** for easy analysis
- **Python CLI and GUI** for scraping addresses
- **Node.js Puppeteer script** for advanced panel scraping and stealth automation
- **Supports proxies, Chrome profiles, and stealth bypasses**

---

## Folder Structure
- `src/scrapers/gmgn_scraper.py` — Python async scraper for addresses
- `scripts/gmgn_cli.py` — Command-line interface for scraping addresses
- `scripts/gmgn_gui.py` — Tkinter GUI for scraping addresses
- `node_scraper/gmgn_puppeteer.js` — Node.js Puppeteer script for scraping panels and addresses
- `output/` — Scraped CSV/JSON data (addresses, panels, PnL, tokens

---

## What Does It Scrape?
### 1. **Wallet Addresses**
- Extracts Solana wallet addresses from GMGN trade pages using Playwright (Python) or Puppeteer (Node.js)
- Uses robust selectors and clipboard reading to bypass site protections
- Results saved to `output/gmgn_addresses.csv`

### 2. **Panels & Trading Data** (Node.js only)
- Scrapes trading panels, Recent PnL, and Deployed Tokens
- Saves structured data to `output/panels/` as JSON and CSV:
  - `panels.json`, `panels_data.json`
  - `recentpnl.json`, `recentpnl_data.json`, `recentpnl.csv`
  - `deployedtokens.json`, `deployedtokens_data.json`, `deployedtokens.csv`

---

## How Does It Work?
### Python Scraper
- Uses Playwright for browser automation
- Extracts addresses via HTML parsing and clipboard
- CLI: `python scripts/gmgn_cli.py --url <GMGN_URL> --count <N> --out <CSV_PATH>`
- GUI: Run `python scripts/gmgn_gui.py` for a desktop app

### Node.js Scraper
- Uses Puppeteer Extra with Stealth plugin to bypass bot detection
- Scrapes panels, tables, and addresses
- CLI: `node node_scraper/gmgn_puppeteer.js --url <GMGN_URL> --count <N> --outdir <OUTPUT_DIR>`
- Supports Chrome profiles, proxies, and CDP attach

---

## Installation
### Python
1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   python -m playwright install
   ```
2. Run CLI or GUI as above

### Node.js
1. Install dependencies:
   ```powershell
   cd node_scraper
   npm install
   ```
2. Run Puppeteer script as above

---

## Output Files
- `output/gmgn_addresses.csv` — List of scraped wallet addresses
- `output/panels/` — JSON/CSV files for panels, PnL, tokens

---

## Advanced Usage
- **Proxies:** Pass `--proxy <proxy_url>` to use a proxy
- **Chrome Profiles:** Pass `--profile <profile_path>` for persistent sessions
- **Headless/Stealth:** Toggle `--headless true` for background scraping
- **CDP Attach:** Use `--cdp <ws://...>` to connect to running Chrome

---

## Troubleshooting
- If Playwright browsers are missing, run: `python -m playwright install`
- For Puppeteer, ensure Chrome is installed and path is correct
- Check logs in `logs/` for details

---

## License
MIT

---

## Author
Bilal Alam
