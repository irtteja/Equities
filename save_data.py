"""Fetch all NSE indices + available constituents and save to nse_data.json."""

import csv
import io
import json
import sys
import time
from datetime import datetime
import anthropic
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

    # Resume from existing checkpoint if present
    try:
        with open(out_file) as f:
            data = json.load(f)
        constituents: dict[str, list] = data.get("constituents", {})
        indices: list[dict] = data.get("indices", [])
        constituent_map: dict[str, str] = data.get("constituent_map", {})
        pending: list[str] = data.get("pending", [])
        pending = [p for p in pending if p not in constituents]
        print(f"Resuming: {len(constituents)} done, {len(pending)} pending")
    except FileNotFoundError:
        constituents = {}
        indices = []
        constituent_map = {}
        pending = []
        data = {}

    print("Connecting to NSE India...")
    session = nse_session()

    if not indices:
        print("Fetching indices...")
        indices = fetch_indices(session)
        print(f"  {len(indices)} indices fetched")

    map_from_checkpoint = bool(constituent_map)

    if not constituent_map:
        print("Building constituent map...")
        constituent_map = _build_constituent_map(indices, session)
        print(f"  {len(constituent_map)} indices with constituent CSV")
    elif map_from_checkpoint:
        # On subsequent runs, check for brand-new indices the map hasn't seen yet
        new_indices = [
            d for d in indices
            if d["index"] not in constituent_map and d["index"] not in constituents
        ]
        if new_indices:
            print(f"  Discovering {len(new_indices)} new indices...")
            constituent_map.update(_build_constituent_map(new_indices, session))

    if not pending:
        # First run or after new indices are discovered: queue all uncompleted
        pending = [name for name in constituent_map if name not in constituents]

    data = {
        "fetched_at": data.get("fetched_at") or datetime.now().isoformat(),
        "indices": indices,
        "constituent_map": constituent_map,
        "constituents": constituents,
        "pending": pending,
        "stocks": data.get("stocks", {}),
    }
    save(out_file, data)

    print(f"Fetching {len(pending)} constituent lists...")

    stocks_master: dict[str, dict] = data.get("stocks", {})

    for index_name in list(pending):
        filename = constituent_map[index_name]
        try:
            rows = fetch_constituents(filename)
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
            save(out_file, data)
            print(f"  {index_name}: {len(symbols)} stocks")
        except Exception as e:
            print(f"  {index_name}: FAILED — {e}", file=sys.stderr)

    data["pending"] = pending
    save(out_file, data)

    total_stocks = sum(len(v) for v in constituents.values())
    print(f"\nSaved to {out_file}")
    print(f"  {len(indices)} indices, {len(constituents)}/{len(constituent_map)} constituent lists, {total_stocks} stock records")

    if not pending:
        print("Exporting CSVs...")
        export_csv(data)

    if pending:
        print(f"  Still pending: {', '.join(pending)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
