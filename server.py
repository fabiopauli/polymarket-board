#!/usr/bin/env python3
"""
Polymarket FastAPI Web Server

Serves a browser UI at / and JSON/SSE endpoints at /api/events.

Usage:
    uv run uvicorn server:app --host 0.0.0.0 --port 8000
    uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload  # dev
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

import dashboard as _dash
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ─── Configuration ─────────────────────────────────────────────────────────────

# Allow overriding the binary path via env var; fall back to dashboard.py default
_dash.PM_BIN = os.environ.get("PM_BIN", _dash.PM_BIN)

CACHE_TTL = int(os.environ.get("PM_CACHE_TTL", "30"))  # seconds

# ─── Cache ─────────────────────────────────────────────────────────────────────

# { limit: (timestamp, result_list) }
_cache: dict[int, tuple[float, list[dict]]] = {}
_cache_lock = asyncio.Lock()


async def get_events(limit: int) -> list[dict]:
    """Fetch events with TTL cache and stampede protection."""
    now = time.monotonic()
    async with _cache_lock:
        if limit in _cache:
            ts, data = _cache[limit]
            if now - ts < CACHE_TTL:
                return data
        # Cache miss or stale — fetch in thread pool (blocking subprocess)
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _dash.fetch_events, limit)
        _cache[limit] = (now, data)
        return data


# ─── Serialisation helpers ─────────────────────────────────────────────────────

def fmt_delta_plain(delta) -> dict:
    """Return delta as a JSON-safe dict with text + direction."""
    if delta is None:
        return {"text": "—", "direction": "flat"}
    try:
        cents = float(delta) * 100
    except (ValueError, TypeError):
        return {"text": "—", "direction": "flat"}
    if abs(cents) < 0.05:
        return {"text": "—", "direction": "flat"}
    sign = "+" if cents > 0 else ""
    arrow = "▲" if cents > 0 else "▼"
    direction = "up" if cents > 0 else "down"
    return {"text": f"{arrow}{sign}{cents:.1f}", "direction": direction}


def _all_contenders(event: dict) -> list[dict]:
    """Return all contenders (markets) sorted by YES price descending."""
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
            "endDate": m.get("endDateIso") or m.get("endDate") or "",
        })
    parsed.sort(key=lambda c: c["yes"], reverse=True)
    return parsed


def events_to_json(events: list[dict]) -> dict:
    """Convert raw event dicts to the API response shape."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = []
    for idx, event in enumerate(events, 1):
        contenders_raw = _all_contenders(event)
        contenders = [
            {
                "name": c["name"],
                "price": _dash.fmt_price_cents(c["yes"]) if c["yes"] > 0 else "",
                "delta": fmt_delta_plain(c["delta"]),
                "endDate": c["endDate"],
            }
            for c in contenders_raw
        ]
        try:
            volume_raw = float(event.get("volumeNum") or event.get("volume") or 0)
        except (ValueError, TypeError):
            volume_raw = 0.0
        try:
            volume24h_raw = float(event.get("volume24hr") or 0)
        except (ValueError, TypeError):
            volume24h_raw = 0.0
        result.append(
            {
                "rank": idx,
                "title": event.get("title") or "?",
                "volume": _dash.fmt_vol(event.get("volume")),
                "volume24h": _dash.fmt_vol(event.get("volume24hr")),
                "volumeRaw": volume_raw,
                "volume24hRaw": volume24h_raw,
                "endDate": event.get("endDateIso") or event.get("endDate") or "",
                "contenderCount": len(contenders_raw),
                "contenders": contenders,
            }
        )
    return {"ts": ts, "ttl": CACHE_TTL, "events": result}


# ─── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Polymarket Board", version="0.1.0")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("static/index.html")


@app.get("/new", include_in_schema=False)
async def new_board():
    return FileResponse("static/new.html")


@app.get("/api/events")
async def api_events(limit: int = Query(10, ge=1, le=100)):
    """Return a JSON snapshot of the top-N events."""
    events = await get_events(limit)
    return events_to_json(events)


async def _sse_generator(limit: int) -> AsyncGenerator[str, None]:
    """Yield SSE frames: immediate snapshot, then every CACHE_TTL seconds."""
    while True:
        events = await get_events(limit)
        payload = events_to_json(events)
        yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(CACHE_TTL)


@app.get("/api/events/stream")
async def api_events_stream(limit: int = Query(10, ge=1, le=100)):
    """Server-Sent Events stream of top-N events, refreshed every CACHE_TTL seconds."""
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable nginx proxy buffering
    }
    return StreamingResponse(
        _sse_generator(limit),
        media_type="text/event-stream",
        headers=headers,
    )
