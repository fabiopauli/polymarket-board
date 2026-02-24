[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)](Dockerfile)

# Polymarket Board

A terminal + browser dashboard for [Polymarket](https://polymarket.com) prediction markets.
Shows the top events by volume with live prices, 24 h changes, and per-event contenders.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  POLYMARKET  Top Events    ●live    next: 28s    2026-02-24  16:30 UTC       │
├── search [___________]  limit [20▾]  contenders [1|2|3|4|5]  Export CSV  ────┤
│  # Event                   Total     24h  #1            Prc¢  Δ24h           │
│  1 US Presidential 2028   $707M     $8M  Gavin Newsom   27¢  ▼-0.4           │
│  2 Fed Rate Mar 2026       $312M     $3M  Hold           61¢  ▲+1.2          │
│  …                                                                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Classic (`/`) | Our Board (`/new`) |
|---------|:---:|:---:|
| Dark monospace theme | ✓ | ✓ |
| Live SSE auto-refresh | ✓ | — |
| Polling with countdown | — | ✓ |
| Scrollable event title cell | — | ✓ |
| Expandable contender detail | — | ✓ |
| Sort by any column | — | ✓ |
| Search / filter | — | ✓ |
| Limit / contender controls | URL param only | UI controls |
| URL state (bookmarkable) | partial | ✓ |
| Export CSV | — | ✓ |
| Default events shown | 10 | 20 |

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | ≥ 3.11 | `python3 --version` |
| Git | any | with submodule support |
| Rust / Cargo | stable | only needed to build the CLI binary |
| `uv` | any | recommended; or use `pip` |

---

## Installation

### 1. Clone the repo (with submodule)

```bash
git clone --recursive https://github.com/fabiopauli/polymarket-board
cd polymarket-board
```

If you already cloned without `--recursive`:

```bash
git submodule update --init --recursive
```

### 2. Build the Polymarket CLI from source

> **Why from source?** The pre-built binary requires **GLIBC ≥ 2.38** (Ubuntu 23.04+, Fedora 38+).
> On Debian 12, Ubuntu 22.04, or WSL2 with an older base image you will see:
>
> ```
> /lib/x86_64-linux-gnu/libc.so.6: version 'GLIBC_2.38' not found
> ```
>
> Building from source avoids this entirely.

Install Rust (skip if already installed):

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

Build the CLI:

```bash
cd polymarket-cli
~/.cargo/bin/cargo build --release   # ~5 min on first run
cd ..
```

Verify:

```bash
./polymarket-cli/target/release/polymarket --version
```

### 3. Install Python dependencies

With `uv` (recommended):

```bash
uv sync
```

With plain `pip`:

```bash
pip install fastapi "uvicorn[standard]" rich aiofiles
```

---

## Running

### Terminal dashboard

```bash
# Static snapshot, top 10 events
python3 dashboard.py --limit 10

# Auto-refresh every 30 s
python3 dashboard.py --limit 10 --refresh 30
```

### Web server

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

| URL | Description |
|-----|-------------|
| `http://localhost:8000/` | Classic Karpathy-style view (SSE live) |
| `http://localhost:8000/new` | Enhanced board (controls, sort, expand) |
| `http://localhost:8000/api/events?limit=20` | Raw JSON |

Add `--reload` for hot-reloading during development.

### Docker

```bash
# Build image (includes Rust CLI compilation — takes a few minutes)
docker build -t polymarket-board .

# Run
docker run -p 8000:8000 polymarket-board

# With custom TTL
docker run -p 8000:8000 -e PM_CACHE_TTL=60 polymarket-board
```

---

## Deploy to Railway

> Railway auto-detects the `Dockerfile` and `railway.toml` — no extra config needed.

1. **Fork / push** this repo to GitHub.
2. Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo**.
3. Select your fork. Railway will build the Docker image automatically.
4. (Optional) Set environment variables in the Railway dashboard:

   | Variable | Value | Description |
   |----------|-------|-------------|
   | `PM_CACHE_TTL` | `30` | Seconds between fresh data fetches |
   | `PORT` | _(set by Railway)_ | Do not override — Railway injects this |

5. Once deployed, Railway shows a public URL. Visit `<url>/new` for the enhanced board.

**Health check:** Railway pings `GET /api/events` (configured in `railway.toml`).

---

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `PM_BIN` | `polymarket-cli/target/release/polymarket` | Path to the CLI binary |
| `PM_CACHE_TTL` | `30` | Seconds between fresh CLI calls |

Example:

```bash
PM_BIN=/usr/local/bin/polymarket PM_CACHE_TTL=60 \
  uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

---

## Web UI

### `/` — Classic view

Minimal Karpathy-style board. Connects via **Server-Sent Events** (SSE) for real-time updates.
Falls back to 30 s polling if SSE is unavailable.

URL params: `?limit=N` (default 10).

### `/new` — Enhanced board

Full-featured interactive board.

| URL param | Default | Options |
|-----------|---------|---------|
| `?limit=` | `20` | 1–100 |
| `?n=` | `5` | 1–5 (contenders per row) |
| `?sort=` | rank | `rank`, `title`, `volume`, `volume24h` |
| `?search=` | _(none)_ | filter text |

Features:
- **Scrollable event title** — long titles scroll horizontally within the cell
- **Click any row** to expand all contenders in a responsive card grid
- **Click column headers** to sort (click again to reverse)
- **Export CSV** downloads the current filtered/sorted view

---

## Architecture

```
Browser  ──SSE──►  FastAPI (server.py)
         ──poll─►      │
                       │  asyncio.Lock + TTL cache (PM_CACHE_TTL s)
                       │
                       ▼
              dashboard.py (fetch_events, _all_contenders, fmt_*)
                       │
                       ▼
          polymarket-cli/target/release/polymarket  (subprocess)
                       │
                       ▼
              Polymarket public API (CLOB / events)
```

- `dashboard.py` is **imported** by `server.py` — no code duplication.
- The subprocess call is blocking I/O; `server.py` offloads it via
  `loop.run_in_executor(None, ...)` so it never blocks the async event loop.
- A single `asyncio.Lock` prevents cache stampede when multiple tabs connect.
- `server.py` calls `_all_contenders()` (all markets, not capped at 5) so the
  browser can display any N contenders without a second fetch.

---

## Troubleshooting

### `GLIBC_2.38 not found`

Build the CLI from source as described in **Installation → Step 2**.

### `cargo: command not found`

```bash
source ~/.cargo/env
# or permanently:
echo 'source ~/.cargo/env' >> ~/.bashrc
```

### Port 8000 already in use

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8080
```

### WSL2: can't reach the server from Windows

Use `http://localhost:8000` — WSL2 forwards localhost automatically on modern
Windows versions. If that fails, find your WSL IP with `ip addr show eth0` and
use that address.

### Docker build fails on `cargo build`

The Dockerfile clones polymarket-cli directly from GitHub during build, so an
internet connection is required. If you are behind a proxy, pass:

```bash
docker build --build-arg https_proxy=$https_proxy -t polymarket-board .
```

### No data / empty table

```bash
# Test the CLI directly
./polymarket-cli/target/release/polymarket -o json events list --active true --limit 5
```

If that returns data, the server should work. If it hangs or errors, check your
internet connection (the CLI fetches from Polymarket's public API).

---

## Contributing

PRs welcome. For local development:

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag watches for file changes and restarts the server automatically.
