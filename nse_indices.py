"""NSE India indices agent — Claude reasons over live NSE data."""

import json
import sys
import requests
import anthropic

MODEL = "claude-opus-5-5"

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
            "INDICES ELIGIBLE IN DERIVATIVES, SECTORAL INDICES, "
            "THEMATIC INDICES, STRATEGY INDICES, FIXED INCOME INDICES."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Optional filter. One of: 'BROAD MARKET INDICES', "
                        "'INDICES ELIGIBLE IN DERIVATIVES', 'SECTORAL INDICES', "
                        "'THEMATIC INDICES', 'STRATEGY INDICES', "
                        "'FIXED INCOME INDICES'. Omit to fetch all."
                    ),
                }
            },
            "required": [],
        },
    }
]


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": NSE_HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s.get("https://www.nseindia.com/", timeout=15)
    s.headers.update(NSE_HEADERS)
    return s


def fetch_nse_indices(category: str | None = None) -> list[dict]:
    session = _nse_session()
    resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
    resp.raise_for_status()
    data = resp.json()["data"]
    if category:
        data = [d for d in data if d.get("key", "").upper() == category.upper()]
    fields = [
        "key", "index", "indexSymbol", "last", "variation", "percentChange",
        "open", "high", "low", "previousClose", "yearHigh", "yearLow",
        "pe", "pb", "dy", "advances", "declines",
    ]
    return [{f: d[f] for f in fields if f in d} for d in data]


def run_tool(name: str, tool_input: dict) -> str:
    if name == "fetch_nse_indices":
        return json.dumps(fetch_nse_indices(tool_input.get("category")))
    return json.dumps({"error": f"Unknown tool: {name}"})


def ask(question: str) -> str:
    """Send a question to the NSE agent; returns Claude's final answer."""
    # Zero-arg client — resolves credentials from the session automatically
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=(
                "You are a financial data agent for NSE India. "
                "Use fetch_nse_indices whenever you need live index data. "
                "Present numbers clearly: commas for thousands, two decimal places, "
                "+ sign for positive changes. Group by category when listing many."
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
