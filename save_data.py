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


def fetch_indices(session: requests.Session) -> list[dict]:
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    return resp.json()["data"]


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


def main() -> None:
    out_file = "nse_data.json"

    # Resume from existing checkpoint if present
    try:
        with open(out_file) as f:
            data = json.load(f)
        constituents: dict[str, list[dict]] = data.get("constituents", {})
        indices: list[dict] = data.get("indices", [])
        # pending: indices not yet successfully fetched
        pending: list[str] = data.get("pending", list(CONSTITUENT_CSV.keys()))
        pending = [p for p in pending if p not in constituents]  # drop already done
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

    for index_name in list(pending):
        filename = CONSTITUENT_CSV[index_name]
        try:
            stocks = fetch_constituents(filename)
            constituents[index_name] = stocks
            pending.remove(index_name)
            data["constituents"] = constituents
            data["pending"] = pending
            save(out_file, data)  # checkpoint: persist success + updated pending
            print(f"  {index_name}: {len(stocks)} stocks")
        except Exception as e:
            print(f"  {index_name}: FAILED — {e}", file=sys.stderr)

    data["pending"] = pending
    save(out_file, data)

    total_stocks = sum(len(v) for v in constituents.values())
    print(f"\nSaved to {out_file}")
    print(f"  {len(indices)} indices, {len(constituents)}/{len(CONSTITUENT_CSV)} constituent lists, {total_stocks} stock records")
    if pending:
        print(f"  Still pending: {', '.join(pending)}", file=sys.stderr)
        sys.exit(1)  # signal to caller that work remains


if __name__ == "__main__":
    main()
