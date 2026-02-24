#!/usr/bin/env python3
"""
Polymarket Terminal Dashboard
Shows top events by total volume, with top-5 contenders, prices in cents, and 24h Δ.
Usage: python3 dashboard.py [--limit N] [--refresh SECONDS]
"""

import json
import subprocess
import sys
import time
import argparse
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich import box

PM_BIN = "/home/fipauli/polymarket/polymarket-cli/target/release/polymarket"
console = Console()

TOP_N_CONTENDERS = 5


# ─── Data fetching ────────────────────────────────────────────────────────────

def fetch_events(limit: int = 10) -> list[dict]:
    """Fetch active events sorted by volume (fetches extra to get real top-N)."""
    fetch_count = max(limit * 5, 100)
    result = subprocess.run(
        [PM_BIN, "-o", "json", "events", "list",
         "--active", "true", "--limit", str(fetch_count)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]Error:[/] {result.stderr.strip()}")
        return []
    try:
        data = json.loads(result.stdout)
        data.sort(key=lambda e: float(e.get("volume") or 0), reverse=True)
        return data[:limit]
    except json.JSONDecodeError as exc:
        console.print(f"[red]JSON error:[/] {exc}")
        return []


def top_contenders(event: dict) -> list[dict]:
    """Return the top-N contenders (markets) sorted by YES price descending."""
    markets = event.get("markets") or []
    parsed = []
    for m in markets:
        try:
            prices = json.loads(m.get("outcomePrices") or "[0,1]")
            yes = float(prices[0])
        except (json.JSONDecodeError, IndexError, ValueError):
            yes = 0.0
        parsed.append({
            "name": m.get("groupItemTitle") or m.get("question") or "?",
            "yes": yes,
            "delta": m.get("oneDayPriceChange"),
        })
    parsed.sort(key=lambda c: c["yes"], reverse=True)
    return parsed[:TOP_N_CONTENDERS]


# ─── Formatting helpers ────────────────────────────────────────────────────────

def fmt_vol(v) -> str:
    try:
        n = float(v or 0)
    except (ValueError, TypeError):
        return "—"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"${n / 1_000:.0f}K"
    return f"${n:.0f}"


def fmt_price_cents(yes: float) -> str:
    """Format YES price as cents: <1¢ / 94¢ / 100¢."""
    cents = yes * 100
    if cents < 1:
        return "<1¢"
    return f"{cents:.0f}¢"


def fmt_delta(delta) -> Text:
    """Format 24h price change in cents with colour."""
    if delta is None:
        return Text("—", style="dim")
    try:
        cents = float(delta) * 100
    except (ValueError, TypeError):
        return Text("—", style="dim")
    if abs(cents) < 0.05:
        return Text("—", style="dim")
    sign = "+" if cents > 0 else ""
    arrow = "▲" if cents > 0 else "▼"
    color = "green" if cents > 0 else "red"
    return Text(f"{arrow}{sign}{cents:.1f}", style=color)


def truncate(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ─── Table builder ─────────────────────────────────────────────────────────────

def calc_layout(width: int) -> tuple[int, int, int]:
    """Return (num_contenders, name_col_width, event_col_width) for a given terminal width."""
    # Column widths (content + rich 1-char padding each side = +2 per col):
    #   #(3) + Event(35) + Total(9) + 24h(8) = 55 content
    #   separators between cols: (4 fixed cols + n*3 contender cols - 1) spaces
    #   Per contender: name_w + price(5) + delta(7) content
    PRICE_W   = 5   # e.g. "27¢", "100¢", "<1¢"
    DELTA_W   = 7   # e.g. "▼-0.4", "▲+1.5", "—"
    FIXED_COLS_W = 3 + 35 + 9 + 8  # # + Event + Total + 24h
    MIN_NAME_W   = 8
    EVENT_W      = 35

    # Separator count: between fixed cols (3) + per contender (2 separators: name|price|delta)
    # Total separators = 3 + n*2 + n (one between each contender group and next) roughly
    # Simpler: each "column" in rich is separated by 1 space, total seps = total_cols - 1
    # total_cols = 4 + n*3; seps = 3 + n*3
    # total = FIXED_COLS_W + n*(MIN_NAME_W + PRICE_W + DELTA_W) + (3 + n*3) + 2 (pad_edge)

    def total_width(n, name_w):
        seps = 3 + n * 3
        return FIXED_COLS_W + n * (name_w + PRICE_W + DELTA_W) + seps + 2

    n = 0
    for k in range(TOP_N_CONTENDERS, 0, -1):
        if total_width(k, MIN_NAME_W) <= width:
            n = k
            break
    if n == 0:
        n = 1

    # Distribute leftover space into name columns
    leftover = width - total_width(n, MIN_NAME_W)
    name_w = MIN_NAME_W + leftover // n

    return n, name_w, EVENT_W


def build_table(events: list[dict]) -> Table:
    width = console.width or 200
    n_cont, name_w, event_w = calc_layout(width)

    table = Table(
        box=box.SIMPLE_HEAVY,
        border_style="bright_black",
        header_style="bold bright_white",
        show_edge=True,
        pad_edge=True,
        expand=False,
        title=None,
    )

    # Fixed columns
    table.add_column("#",     width=3,       justify="right", style="dim",      no_wrap=True)
    table.add_column("Event", width=event_w, justify="left",  style="bold",     no_wrap=True)
    table.add_column("Total", width=9,       justify="right",                   no_wrap=True)
    table.add_column("24h",   width=8,       justify="right", style="dim cyan", no_wrap=True)

    # Contender groups: Name | Prc¢ | Δ24h
    for i in range(1, n_cont + 1):
        table.add_column(f"#{i}",   width=name_w, justify="left",  style="italic", no_wrap=True)
        table.add_column("Prc¢",    width=5,      justify="right",                 no_wrap=True)
        table.add_column("Δ24h",    width=7,      justify="right",                 no_wrap=True)

    for idx, event in enumerate(events, 1):
        contenders = top_contenders(event)
        # Pad to n_cont
        while len(contenders) < n_cont:
            contenders.append({"name": "", "yes": 0, "delta": None})

        row: list = [
            str(idx),
            truncate(event.get("title") or "?", event_w),
            fmt_vol(event.get("volume")),
            fmt_vol(event.get("volume24hr")),
        ]
        for c in contenders[:n_cont]:
            row.append(truncate(c["name"], name_w))
            row.append(fmt_price_cents(c["yes"]) if c["yes"] > 0 else "")
            row.append(fmt_delta(c["delta"]))

        table.add_row(*row)

    return table


def build_header(n: int, ts: datetime) -> Panel:
    t = Text()
    t.append("  POLYMARKET  ", style="bold black on bright_cyan")
    t.append(f"  Top {n} Events by Volume  ", style="bold bright_white")
    t.append(f"  {ts.strftime('%b %d  %H:%M')}  ", style="dim cyan")
    return Panel(t, box=box.HEAVY, border_style="cyan", padding=(0, 1))


def build_footer() -> Panel:
    t = Text()
    t.append("  Deltas: ", style="dim")
    t.append("▲ up ", style="green")
    t.append("▼ down ", style="red")
    t.append("  Prices = probability in cents  ", style="dim")
    t.append("  [Ctrl-C] quit", style="dim bright_black")
    return Panel(t, box=box.SIMPLE, border_style="bright_black", padding=(0, 0))


# ─── Main ─────────────────────────────────────────────────────────────────────

def render(limit: int):
    from rich.console import Group
    now = datetime.now()
    events = fetch_events(limit)
    if not events:
        return Panel("[red]No data available.[/]")
    return Group(build_header(len(events), now), build_table(events), build_footer())


def main():
    parser = argparse.ArgumentParser(description="Polymarket Terminal Dashboard")
    parser.add_argument("--limit",   type=int, default=10,  help="Events to show (default 10)")
    parser.add_argument("--refresh", type=int, default=None, metavar="SEC",
                        help="Auto-refresh interval in seconds")
    args = parser.parse_args()

    console.print(Panel("[cyan]Fetching Polymarket event data…[/]", box=box.SIMPLE))

    if args.refresh:
        with Live(render(args.limit), console=console, screen=True, refresh_per_second=1) as live:
            try:
                while True:
                    time.sleep(args.refresh)
                    live.update(render(args.limit))
            except KeyboardInterrupt:
                pass
    else:
        console.print(render(args.limit))


if __name__ == "__main__":
    main()
