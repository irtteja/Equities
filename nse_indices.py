"""Fetch and display all NSE India indices."""

import requests
import json
from datetime import datetime


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}


def get_session() -> requests.Session:
    """Create a session with NSE cookies by hitting the homepage first."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.get("https://www.nseindia.com/", timeout=15)
    session.headers.update(HEADERS)
    return session


def fetch_indices(session: requests.Session) -> list[dict]:
    """Fetch all NSE indices."""
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    return resp.json()["data"]


def print_indices(indices: list[dict]) -> None:
    """Print indices grouped by category."""
    from itertools import groupby

    print(f"\nNSE Indices  —  {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    print("=" * 80)

    by_category = {}
    for idx in indices:
        by_category.setdefault(idx["key"], []).append(idx)

    for category, items in sorted(by_category.items()):
        print(f"\n{category}")
        print("-" * 80)
        print(f"{'Index':<40} {'Last':>12} {'Change':>10} {'%Chg':>8}")
        print(f"{'-----':<40} {'----':>12} {'------':>10} {'----':>8}")
        for item in items:
            chg_sign = "+" if item["variation"] >= 0 else ""
            pct_sign = "+" if item["percentChange"] >= 0 else ""
            print(
                f"{item['index']:<40} "
                f"{item['last']:>12,.2f} "
                f"{chg_sign}{item['variation']:>9,.2f} "
                f"{pct_sign}{item['percentChange']:>7.2f}%"
            )

    print(f"\nTotal: {len(indices)} indices")


def main() -> None:
    print("Connecting to NSE India...")
    session = get_session()
    print("Fetching indices...")
    indices = fetch_indices(session)
    print_indices(indices)


if __name__ == "__main__":
    main()
