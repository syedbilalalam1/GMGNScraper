import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing as a package
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ken_automation.scrapers.gmgn_scraper import scrape_gmgn_sync, save_addresses_to_csv


def main():
    parser = argparse.ArgumentParser(description="Scrape addresses from gmgn.ai and save to CSV")
    parser.add_argument("--url", default="https://gmgn.ai/trade/uZy0WmVx?chain=sol", help="GMGN page URL")
    parser.add_argument("--count", type=int, default=100, help="Expected number of addresses to collect")
    parser.add_argument("--out", type=Path, default=Path("output/gmgn_addresses.csv"), help="Output CSV path")
    args = parser.parse_args()

    addresses = scrape_gmgn_sync(url=args.url, expected_count=args.count)
    save_addresses_to_csv(addresses, args.out)
    print(f"Saved {len(addresses)} addresses to {args.out}")


if __name__ == "__main__":
    main()
