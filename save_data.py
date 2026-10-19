"""Fetch all NSE indices + available constituents and save to nse_data.json."""

import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
import anthropic
import requests

IST = timezone(timedelta(hours=5, minutes=30))

def _now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")

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
    # ── Broad market ──────────────────────────────────────────────────────────
    "NIFTY 50":                         "ind_nifty50list.csv",
    "NIFTY NEXT 50":                    "ind_niftynext50list.csv",
    "NIFTY 100":                        "ind_nifty100list.csv",
    "NIFTY 200":                        "ind_nifty200list.csv",
    "NIFTY 500":                        "ind_nifty500list.csv",
    "NIFTY MIDCAP 50":                  "ind_niftymidcap50list.csv",
    "NIFTY MIDCAP 100":                 "ind_niftymidcap100list.csv",
    "NIFTY MIDCAP 150":                 "ind_niftymidcap150list.csv",
    "NIFTY MIDCAP SELECT":              "ind_niftymidcapselect_list.csv",
    "NIFTY SMALLCAP 50":                "ind_niftysmallcap50list.csv",
    "NIFTY SMALLCAP 100":               "ind_niftysmallcap100list.csv",
    "NIFTY SMALLCAP 250":               "ind_niftysmallcap250list.csv",
    "NIFTY LARGEMIDCAP 250":            "ind_niftylargemidcap250list.csv",
    "NIFTY MIDSMALLCAP 400":            "ind_niftymidsmallcap400list.csv",
    "NIFTY MICROCAP 250":               "ind_niftymicrocap250_list.csv",
    "NIFTY TOTAL MARKET":               "ind_niftytotalmarket_list.csv",
    # ── Sectoral ──────────────────────────────────────────────────────────────
    "NIFTY BANK":                       "ind_niftybanklist.csv",
    "NIFTY IT":                         "ind_niftyitlist.csv",
    "NIFTY AUTO":                       "ind_niftyautolist.csv",
    "NIFTY PHARMA":                     "ind_niftypharmalist.csv",
    "NIFTY FMCG":                       "ind_niftyfmcglist.csv",
    "NIFTY METAL":                      "ind_niftymetallist.csv",
    "NIFTY REALTY":                     "ind_niftyrealtylist.csv",
    "NIFTY HEALTHCARE INDEX":           "ind_niftyhealthcarelist.csv",
    "NIFTY INFRASTRUCTURE":             "ind_niftyinfralist.csv",
    "NIFTY ENERGY":                     "ind_niftyenergylist.csv",
    "NIFTY MEDIA":                      "ind_niftymedialist.csv",
    "NIFTY PSU BANK":                   "ind_niftypsubanklist.csv",
    "NIFTY CPSE":                       "ind_niftycpselist.csv",
    "NIFTY PSE":                        "ind_niftypselist.csv",
    "NIFTY OIL & GAS":                  "ind_niftyoilgaslist.csv",
    "NIFTY CHEMICALS":                  "ind_niftyChemicals_list.csv",
    "NIFTY MIDSMALL HEALTHCARE":        "ind_niftymidsmallhealthcare_list.csv",
    "NIFTY FINANCIAL SERVICES EX-BANK": "ind_niftyfinancialservicesexbank_list.csv",
    "NIFTY REITS & REALTY":             "ind_niftyREITsRealty_list.csv",
    # ── Thematic ──────────────────────────────────────────────────────────────
    "NIFTY MNC":                        "ind_niftymnclist.csv",
    "NIFTY COMMODITIES":                "ind_niftycommoditieslist.csv",
    "NIFTY INDIA CONSUMPTION":          "ind_niftyconsumptionlist.csv",
    "NIFTY CONSUMER DURABLES":          "ind_niftyconsumerdurableslist.csv",
    "NIFTY INDIA MANUFACTURING":        "ind_niftyindiamanufacturing_list.csv",
    "NIFTY INDIA DEFENCE":              "ind_niftyindiadefence_list.csv",
    "NIFTY INDIA TOURISM":              "ind_niftyindiatourism_list.csv",
    "NIFTY INDIA DIGITAL":              "ind_niftyindiadigital_list.csv",
    "NIFTY MOBILITY":                   "ind_niftymobility_list.csv",
    "NIFTY CORE HOUSING":               "ind_niftycorehousing_list.csv",
    "NIFTY CAPITAL MARKETS":            "ind_niftyCapitalMarkets_list.csv",
    "NIFTY TRANSPORTATION & LOGISTICS": "ind_niftytransportationandlogistics_list.csv",
    "NIFTY MIDSMALL INDIA CONSUMPTION": "ind_niftymidsmallindiaconsumption_list.csv",
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

_ARCHIVE_BASE = "https://nsearchives.nseindia.com/content/indices/"

_DISCOVERY_TOOLS = [
    {
        "name": "fetch_page",
        "description": (
            "Fetch a URL and return its text content. Use to get a directory listing from "
            "https://nsearchives.nseindia.com/content/indices/ or to browse NSE index pages "
            "that link to constituent CSV downloads."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "check_url",
        "description": "HEAD request to verify a URL exists. Returns HTTP status code.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
]


def _run_discovery_tool(name: str, tool_input: dict) -> str:
    try:
        ua = {"User-Agent": NSE_HEADERS["User-Agent"]}
        if name == "fetch_page":
            r = requests.get(tool_input["url"], headers=ua, timeout=15)
            return json.dumps({"status": r.status_code, "text": r.text[:10000]})
        if name == "check_url":
            r = requests.head(tool_input["url"], headers=ua, timeout=8)
            return json.dumps({"status": r.status_code})
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _anthropic_client() -> anthropic.Anthropic:
    """Create an Anthropic client using the session ingress token when available."""
    import os
    token_file = os.environ.get("CLAUDE_SESSION_INGRESS_TOKEN_FILE")
    if token_file:
        try:
            with open(token_file) as f:
                return anthropic.Anthropic(auth_token=f.read().strip())
        except OSError:
            pass
    return anthropic.Anthropic()


def discover_csvs_with_agent(unknown_indices: list[str]) -> dict[str, str]:
    """Ask a Claude agent to find constituent CSV filenames for unknown NSE indices."""
    if not unknown_indices:
        return {}

    client = _anthropic_client()
    index_list = "\n".join(f"- {n}" for n in unknown_indices)
    messages = [{"role": "user", "content": (
        f"Find constituent CSV filenames on https://nsearchives.nseindia.com/content/indices/ "
        f"for these NSE indices:\n{index_list}\n\n"
        f"1. First fetch https://nsearchives.nseindia.com/content/indices/ for a directory listing.\n"
        f"2. Match each index name to a filename (all start with 'ind_', end in '.csv').\n"
        f"3. Use check_url to verify any uncertain matches.\n"
        f"4. Reply with ONLY a JSON object: {{\"INDEX NAME\": \"filename.csv\", ...}} "
        f"— only include indices you confirmed. No prose."
    )}]

    while True:
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=4096,
            system=(
                "You are a data discovery agent. Find CSV filenames for NSE index constituent "
                "lists at https://nsearchives.nseindia.com/content/indices/. "
                "Files follow patterns like ind_nifty<name>_list.csv or ind_nifty<name>list.csv. "
                "Respond with valid JSON only — no prose, no markdown."
            ),
            tools=_DISCOVERY_TOOLS,
            messages=messages,
        )

        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn":
            raw = "\n".join(text_parts)
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {}

        if response.stop_reason != "tool_use":
            return {}

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _run_discovery_tool(block.name, block.input),
                })
        messages.append({"role": "user", "content": tool_results})


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

    # Build reverse map: symbol → sorted list of indices
    symbol_to_indices: dict[str, list[str]] = {}
    for index_name, symbols in data["constituents"].items():
        for sym in symbols:
            symbol_to_indices.setdefault(sym, []).append(index_name)
    for sym in symbol_to_indices:
        symbol_to_indices[sym].sort()

    # stocks.csv — one row per stock with all details + indices membership
    stocks = data.get("stocks", {})
    with open("stocks.csv", "w", newline="") as f:
        fieldnames = ["Symbol", "Company Name", "Industry", "Series", "ISIN Code", "Indices"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for sym, info in stocks.items():
            writer.writerow({
                **info,
                "Indices": " | ".join(symbol_to_indices.get(sym, [])),
            })

    # changes.csv — full history of all detected changes
    changes = data.get("changes", [])
    with open("changes.csv", "w", newline="") as f:
        fieldnames = ["Timestamp (IST)", "Type", "Index", "Symbol", "Company Name"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in changes:
            writer.writerow({
                "Timestamp (IST)": c.get("timestamp", ""),
                "Type":            c.get("type", ""),
                "Index":           c.get("index", ""),
                "Symbol":          c.get("symbol", ""),
                "Company Name":    c.get("company", ""),
            })

    print(f"  indices.csv: {len(data['indices'])} rows")
    print(f"  stocks.csv: {len(stocks)} stocks with index membership")
    print(f"  changes.csv: {len(changes)} change records")


def _build_constituent_map(indices: list[dict], session: requests.Session) -> dict[str, str]:
    """
    Return {index_name: csv_filename} for all non-excluded indices.
    Known mappings come from CONSTITUENT_CSV; unknown indices are probed via HEAD requests.
    """
    result: dict[str, str] = {}
    unknown = []
    for d in indices:
        name = d["index"]
        if name in CONSTITUENT_CSV:
            result[name] = CONSTITUENT_CSV[name]
        else:
            unknown.append(name)

    if unknown:
        print(f"  Agent discovering {len(unknown)} unknown indices...", file=sys.stderr)
        discovered = discover_csvs_with_agent(unknown)
        for name, filename in discovered.items():
            result[name] = filename
            print(f"    discovered: {name} → {filename}", file=sys.stderr)
        for name in unknown:
            if name not in discovered:
                print(f"    no CSV: {name}", file=sys.stderr)

    return result


def main() -> None:
    out_file = "nse_data.json"

    # Load checkpoint
    try:
        with open(out_file) as f:
            data = json.load(f)
        constituents: dict[str, list]  = data.get("constituents", {})
        constituent_map: dict[str, str] = data.get("constituent_map", {})
        stocks_master: dict[str, dict]  = data.get("stocks", {})
        changes: list[dict]             = data.get("changes", [])
        # refresh_pending: indices left to re-fetch in the current run
        # if present, we're resuming a partial run; otherwise start fresh
        refresh_pending: list[str] | None = data.get("refresh_pending")
        print(f"Loaded checkpoint: {len(constituents)} indices, {len(stocks_master)} stocks")
    except FileNotFoundError:
        constituents, constituent_map, stocks_master, changes = {}, {}, {}, []
        refresh_pending = None
        data = {}

    print("Connecting to NSE India...")
    session = nse_session()

    print("Fetching indices...")
    indices = fetch_indices(session)
    print(f"  {len(indices)} indices fetched")

    # Update constituent map — discover any brand-new indices
    new_index_names = [d["index"] for d in indices if d["index"] not in constituent_map]
    if new_index_names:
        print(f"  Building constituent map ({len(new_index_names)} new)...")
        constituent_map.update(_build_constituent_map(
            [d for d in indices if d["index"] in new_index_names], session
        ))

    # Detect indices removed from NSE entirely
    current_names = {d["index"] for d in indices}
    ts = _now_ist()
    for removed in set(constituent_map) - current_names:
        print(f"  Index removed from NSE: {removed}")
        changes.append({"timestamp": ts, "type": "index_removed", "index": removed,
                        "symbol": "", "company": ""})
        constituent_map.pop(removed, None)
        constituents.pop(removed, None)

    # First run of this refresh: queue all indices
    if refresh_pending is None:
        refresh_pending = list(constituent_map.keys())

    data = {
        "fetched_at": _now_ist(),
        "indices": indices,
        "constituent_map": constituent_map,
        "constituents": constituents,
        "refresh_pending": refresh_pending,
        "stocks": stocks_master,
        "changes": changes,
    }
    save(out_file, data)

    print(f"Refreshing {len(refresh_pending)} constituent lists...")

    for index_name in list(refresh_pending):
        filename = constituent_map[index_name]
        try:
            rows = fetch_constituents(filename)
            new_symbols: list[str] = []
            for row in rows:
                sym = row.get("Symbol", "").strip()
                if sym:
                    stocks_master[sym] = {
                        "Symbol":       sym,
                        "Company Name": row.get("Company Name", "").strip(),
                        "Industry":     row.get("Industry", "").strip(),
                        "Series":       row.get("Series", "").strip(),
                        "ISIN Code":    row.get("ISIN Code", "").strip(),
                    }
                    new_symbols.append(sym)

            # Diff against stored constituent list
            old_set = set(constituents.get(index_name, []))
            new_set = set(new_symbols)
            ts = _now_ist()
            for sym in new_set - old_set:
                changes.append({"timestamp": ts, "type": "stock_added",
                                 "index": index_name, "symbol": sym,
                                 "company": stocks_master.get(sym, {}).get("Company Name", "")})
            for sym in old_set - new_set:
                changes.append({"timestamp": ts, "type": "stock_removed",
                                 "index": index_name, "symbol": sym,
                                 "company": stocks_master.get(sym, {}).get("Company Name", "")})
            if new_set != old_set:
                print(f"  {index_name}: +{len(new_set-old_set)} -{len(old_set-new_set)}")
            else:
                print(f"  {index_name}: {len(new_symbols)} stocks (no change)")

            constituents[index_name] = new_symbols
            refresh_pending.remove(index_name)
            data.update({"constituents": constituents, "refresh_pending": refresh_pending,
                         "stocks": stocks_master, "changes": changes})
            save(out_file, data)

        except Exception as e:
            print(f"  {index_name}: FAILED — {e}", file=sys.stderr)

    # Detect orphaned stocks (no longer in any index)
    all_symbols = {sym for syms in constituents.values() for sym in syms}
    ts = _now_ist()
    for sym in list(stocks_master):
        if sym not in all_symbols:
            changes.append({"timestamp": ts, "type": "stock_orphaned",
                             "index": "", "symbol": sym,
                             "company": stocks_master[sym].get("Company Name", "")})
            print(f"  Orphaned stock removed: {sym}")
            del stocks_master[sym]

    data.update({"stocks": stocks_master, "changes": changes})

    # Clear refresh_pending only when fully complete
    if not refresh_pending:
        data["refresh_pending"] = None

    save(out_file, data)

    print(f"\nSaved to {out_file}")
    print(f"  {len(indices)} indices, {len(constituents)} constituent lists, "
          f"{len(stocks_master)} unique stocks, {len(changes)} change records")

    print("Exporting CSVs...")
    export_csv(data)

    if refresh_pending:
        print(f"  Still pending: {', '.join(refresh_pending)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
