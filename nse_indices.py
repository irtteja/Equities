"""NSE India indices agent — Claude reasons over live NSE data."""

import csv
import io
import json
import sys
import requests
import anthropic

MODEL = "claude-opus-5-5"

# ── NSE archive: index symbol → CSV filename ───────────────────────────────
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

TOOLS = [
    {
        "name": "fetch_nse_indices",
        "description": (
            "Fetch live NSE India indices from nseindia.com. "
            "Returns all indices with last price, change, % change, open, high, low, "
            "previous close, 52-week high/low, P/E, P/B, dividend yield, "
            "advances/declines. Categories: BROAD MARKET INDICES, "
            "INDICES ELIGIBLE IN DERIVATIVES, SECTORAL INDICES, THEMATIC INDICES."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Optional filter. One of: 'BROAD MARKET INDICES', "
                        "'INDICES ELIGIBLE IN DERIVATIVES', 'SECTORAL INDICES', "
                        "'THEMATIC INDICES'. Omit to fetch all."
                    ),
                }
            },
            "required": [],
        },
    },
    {
        "name": "fetch_index_constituents",
        "description": (
            "Fetch the constituent stocks of a specific NSE index. "
            "Returns each stock's company name, industry/sector, NSE symbol, "
            "series, and ISIN code. "
            f"Supported indices: {', '.join(sorted(CONSTITUENT_CSV.keys()))}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": (
                        "The index name exactly as listed in the description, "
                        "e.g. 'NIFTY 50', 'NIFTY BANK', 'NIFTY IT'."
                    ),
                }
            },
            "required": ["index"],
        },
    },
]


# ── helpers ────────────────────────────────────────────────────────────────

def _nse_session() -> requests.Session:
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


def fetch_nse_indices(category: str | None = None) -> list[dict]:
    session = _nse_session()
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]
    data = [d for d in data if d.get("key", "").upper() not in EXCLUDED_CATEGORIES]
    if category:
        data = [d for d in data if d.get("key", "").upper() == category.upper()]
    fields = [
        "key", "index", "indexSymbol", "last", "variation", "percentChange",
        "open", "high", "low", "previousClose", "yearHigh", "yearLow",
        "pe", "pb", "dy", "advances", "declines",
    ]
    return [{f: d[f] for f in fields if f in d} for d in data]


def fetch_index_constituents(index: str) -> list[dict] | dict:
    filename = CONSTITUENT_CSV.get(index.upper()) or CONSTITUENT_CSV.get(index)
    if not filename:
        # fuzzy match
        key = next(
            (k for k in CONSTITUENT_CSV if index.upper() in k or k in index.upper()),
            None,
        )
        if not key:
            return {
                "error": f"No constituent data for '{index}'.",
                "supported": sorted(CONSTITUENT_CSV.keys()),
            }
        filename = CONSTITUENT_CSV[key]

    url = f"https://nsearchives.nseindia.com/content/indices/{filename}"
    resp = requests.get(url, headers={"User-Agent": NSE_HEADERS["User-Agent"]}, timeout=15)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    return [dict(row) for row in reader]


def run_tool(name: str, tool_input: dict) -> str:
    try:
        if name == "fetch_nse_indices":
            return json.dumps(fetch_nse_indices(tool_input.get("category")))
        if name == "fetch_index_constituents":
            return json.dumps(fetch_index_constituents(tool_input["index"]))
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name, "input": tool_input})


# ── agent loop ─────────────────────────────────────────────────────────────

def ask(question: str) -> str:
    """Run the agentic loop and return Claude's final answer."""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=(
                "You are a financial data agent for NSE India (National Stock Exchange). "
                "Use fetch_nse_indices to get live index prices and market-wide data. "
                "Use fetch_index_constituents to get the stocks inside a specific index. "
                "Present numbers clearly: commas for thousands, two decimal places, "
                "+ sign for positive changes. Group by category when listing many indices."
            ),
            tools=TOOLS,
            messages=messages,
        )

        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn":
            return "\n".join(text_parts)

        if response.stop_reason != "tool_use":
            return "\n".join(text_parts) or f"[stopped: {response.stop_reason}]"

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": run_tool(block.name, block.input),
                })
        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Show me today's top 5 gainers and top 5 losers across all NSE indices."
    )
    print(f"Q: {question}\n")
    print(ask(question))


if __name__ == "__main__":
    main()
