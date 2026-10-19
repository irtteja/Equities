"""Fetch all NSE indices + available constituents and save to nse_data.json."""

import csv
import io
import json
import sys
import time
from datetime import datetime
import requests

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

CONSTITUENT_CSV = {
    "NIFTY 50":                "ind_nifty50list.csv",
    "NIFTY NEXT 50":           "ind_niftynext50list.csv",
    "NIFTY 100":               "ind_nifty100list.csv",
    "NIFTY 200":               "ind_nifty200list.csv",
    "NIFTY 500":               "ind_nifty500list.csv",
    "NIFTY BANK":              "ind_niftybanklist.csv",
    "NIFTY IT":                "ind_niftyitlist.csv",
    "NIFTY AUTO":              "ind_niftyautolist.csv",
    "NIFTY PHARMA":            "ind_niftypharmalist.csv",
    "NIFTY FMCG":              "ind_niftyfmcglist.csv",
    "NIFTY METAL":             "ind_niftymetallist.csv",
    "NIFTY REALTY":            "ind_niftyrealtylist.csv",
    "NIFTY MIDCAP 50":         "ind_niftymidcap50list.csv",
    "NIFTY MIDCAP 100":        "ind_niftymidcap100list.csv",
    "NIFTY MIDCAP 150":        "ind_niftymidcap150list.csv",
    "NIFTY SMALLCAP 50":       "ind_niftysmallcap50list.csv",
    "NIFTY SMALLCAP 100":      "ind_niftysmallcap100list.csv",
    "NIFTY SMALLCAP 250":      "ind_niftysmallcap250list.csv",
    "NIFTY LARGEMIDCAP 250":   "ind_niftylargemidcap250list.csv",
    "NIFTY MIDSMALLCAP 400":   "ind_niftymidsmallcap400list.csv",
    "NIFTY HEALTHCARE INDEX":  "ind_niftyhealthcarelist.csv",
    "NIFTY INFRASTRUCTURE":    "ind_niftyinfralist.csv",
    "NIFTY ENERGY":            "ind_niftyenergylist.csv",
    "NIFTY MEDIA":             "ind_niftymedialist.csv",
    "NIFTY MNC":               "ind_niftymnclist.csv",
    "NIFTY PSU BANK":          "ind_niftypsubanklist.csv",
    "NIFTY CPSE":              "ind_niftycpselist.csv",
    "NIFTY PSE":               "ind_niftypselist.csv",
    "NIFTY COMMODITIES":       "ind_niftycommoditieslist.csv",
    "NIFTY INDIA CONSUMPTION": "ind_niftyconsumptionlist.csv",
    "NIFTY CONSUMER DURABLES": "ind_niftyconsumerdurableslist.csv",
    "NIFTY MICROCAP 250":      "ind_niftymicrocap250_list.csv",
}


def nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.get("https://www.nseindia.com/", timeout=15)
    s.headers.update(NSE_HEADERS)
    return s


EXCLUDED_CATEGORIES = {"STRATEGY INDICES", "FIXED INCOME INDICES"}


def fetch_indices(session: requests.Session) -> list[dict]:
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    return [
        d for d in resp.json()["data"]
        if d.get("key", "").upper() not in EXCLUDED_CATEGORIES
    ]


def fetch_constituents(filename: str, retries: int = 4) -> list[dict]:
    url = f"https://nsearchives.nseindia.com/content/indices/{filename}"
    delay = 2
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(retries):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": NSE_HEADERS["User-Agent"]},
                timeout=15 + attempt * 15,  # 15s, 30s, 45s, 60s
            )
            resp.raise_for_status()
            return list(csv.DictReader(io.StringIO(resp.text)))
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                print(f"    retry {attempt + 1}/{retries - 1} after {delay}s — {e}", file=sys.stderr)
                time.sleep(delay)
                delay *= 2
    raise last_exc


def save(out_file: str, data: dict) -> None:
    tmp = out_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    import os
    os.replace(tmp, out_file)


def export_csv(data: dict) -> None:
    # indices.csv
    with open("indices.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data["indices"][0].keys())
        writer.writeheader()
        writer.writerows(data["indices"])

    # stocks.csv — one row per unique stock
    stocks = data.get("stocks", {})
    with open("stocks.csv", "w", newline="") as f:
        fieldnames = ["Symbol", "Company Name", "Industry", "Series", "ISIN Code"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(stocks.values())

    # index_membership.csv — index → symbol mapping
    with open("index_membership.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index", "Symbol"])
        writer.writeheader()
        for index_name, symbols in data["constituents"].items():
            for sym in symbols:
                writer.writerow({"index": index_name, "Symbol": sym})

    total_memberships = sum(len(v) for v in data["constituents"].values())
    print(f"  indices.csv: {len(data['indices'])} rows")
    print(f"  stocks.csv: {len(stocks)} unique stocks")
    print(f"  index_membership.csv: {total_memberships} rows")


def main() -> None:
    out_file = "nse_data.json"

    # Resume from existing checkpoint if present
    try:
        with open(out_file) as f:
            data = json.load(f)
        constituents: dict[str, list] = data.get("constituents", {})
        indices: list[dict] = data.get("indices", [])
        pending: list[str] = data.get("pending", list(CONSTITUENT_CSV.keys()))
        pending = [p for p in pending if p not in constituents]
        print(f"Resuming: {len(constituents)} done, {len(pending)} pending")
    except FileNotFoundError:
        constituents = {}
        indices = []
        pending = list(CONSTITUENT_CSV.keys())
        data = {}

    if not indices:
        print("Connecting to NSE India...")
        session = nse_session()
        print("Fetching indices...")
        indices = fetch_indices(session)
        print(f"  {len(indices)} indices fetched")
        data = {
            "fetched_at": datetime.now().isoformat(),
            "indices": indices,
            "constituents": constituents,
            "pending": pending,
        }
        save(out_file, data)

    print(f"Fetching {len(pending)} constituent lists...")

    stocks_master: dict[str, dict] = data.get("stocks", {})

    for index_name in list(pending):
        filename = CONSTITUENT_CSV[index_name]
        try:
            rows = fetch_constituents(filename)
            # store unique stocks in master dict, constituents as symbol list
            symbols = []
            for row in rows:
                sym = row.get("Symbol", "").strip()
                if sym:
                    stocks_master[sym] = {
                        "Symbol": sym,
                        "Company Name": row.get("Company Name", "").strip(),
                        "Industry": row.get("Industry", "").strip(),
                        "Series": row.get("Series", "").strip(),
                        "ISIN Code": row.get("ISIN Code", "").strip(),
                    }
                    symbols.append(sym)
            constituents[index_name] = symbols
            pending.remove(index_name)
            data["stocks"] = stocks_master
            data["constituents"] = constituents
            data["pending"] = pending
            save(out_file, data)  # checkpoint: persist success + updated pending
            print(f"  {index_name}: {len(symbols)} stocks")
        except Exception as e:
            print(f"  {index_name}: FAILED — {e}", file=sys.stderr)

    data["pending"] = pending
    save(out_file, data)

    total_stocks = sum(len(v) for v in constituents.values())
    print(f"\nSaved to {out_file}")
    print(f"  {len(indices)} indices, {len(constituents)}/{len(CONSTITUENT_CSV)} constituent lists, {total_stocks} stock records")

    if not pending:
        print("Exporting CSVs...")
        export_csv(data)

    if pending:
        print(f"  Still pending: {', '.join(pending)}", file=sys.stderr)
        sys.exit(1)  # signal to caller that work remains


if __name__ == "__main__":
    main()
