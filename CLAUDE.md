# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-process FastAPI app that powers a live classroom scoreboard. It tails
log files, detects SYSLOG / RADIUS / TACACS+ activity, maps router IPs and Digi
hostnames to participants, and pushes scoreboard updates to browsers over a
WebSocket. State is in-memory by default.

## Commands

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Run (demo mode is the default; reads sample_logs.txt on a loop)
python app.py                 # http://localhost:8000

# Run all tests (stdlib unittest, no pytest)
python -m unittest tests.test_syslog
# Single test
python -m unittest tests.test_syslog.SyslogParserTests.test_decoded_tcpdump_packet
```

There is no linter or build step configured.

## Configuration via environment variables

Behavior is driven almost entirely by env vars read in `app.py`, not flags:

- `LOG_MODE` — `demo` (default), `live`, or `off`
- `DEMO_LOOP` — `false` to play the sample file once
- `LOG_FILE` — single log file (legacy; works in demo and live)
- `LIVE_LOG_FILES` — comma-separated files to tail in live mode (defaults to
  `/tmp/digi-scoreboard-syslog.log`, `/var/log/syslog`, `/var/log/tac_plus_acct.log`)
- `LIVE_FROM_START` — `true` to process existing lines instead of seeking to EOF
- `STATE_FILE` — path to persist state as JSON (never point this at `users.json`)

The two JSON config files (`users.json`, `scoring.json`) are loaded **once at
startup**; the app must be restarted after editing them.

## Architecture

Three modules, layered, no framework magic beyond FastAPI wiring:

1. **`parsers.py`** — pure functions, no state. `parse_log_events(line)` is the
   single entry point: it runs a line through every parser and returns a list of
   normalized event dicts. The normalized event shape is the contract between
   layers: `{participant_ip|participant_id, service, status, event_type,
   username, raw, ...}`. Key behavioral rule: a stored Digi syslog line can map
   to *multiple* events (syslog + a web-session radius/tacacs event), but once a
   line is recognized as stored syslog the independent AAA/FreeRADIUS/TACACS+
   parsers are skipped to avoid duplicate accounting. SSH/PAM copies in syslog
   are deliberately ignored to prevent double-counting TACACS+.

2. **`state.py`** (`ScoreboardState`) — the only stateful component, guarded by a
   single `asyncio.Lock`. `apply_event()` resolves a participant, applies scoring,
   and returns `True` if anything changed. Participant resolution order in
   `_resolve_participant`: exact alias/IP/hostname match first, then
   longest-prefix subnet match (networks are sorted by prefixlen descending at
   init). Scoring distinguishes `one_time_services` (syslog: scores once, stays
   green forever) from first-login services (radius/tacacs: score on first green;
   logout flips status green→`logged`, never removes points). `earned` tracks
   whether points were already awarded so re-logins don't double-score.

3. **`app.py`** — FastAPI app + async log readers. `demo_log_reader` /
   `live_log_reader` tasks are started in the `lifespan` context manager (one
   task per live file; handles rotation/truncation via inode + size checks).
   Every line goes through `process_log_line` → `apply_event` → `broadcast_state`.
   `ConnectionManager` broadcasts snapshots to all WebSocket clients. Unknown
   source IPs/hostnames are logged once each (deduped, capped at 100) rather than
   erroring — they're expected during a live demo.

## Endpoints

- `GET /` — serves `static/index.html` (frontend is vanilla `static/app.js` + WebSocket)
- `GET /api/state`, `POST /api/reset`, `POST /api/event` (manual event; 400 on unknown IP)
- `WS /ws` — server-driven; client sends keepalives, server pushes snapshots

## Adapting to real logs

When real device logs arrive, edit the regexes/parser bodies in `parsers.py`.
Each parser must keep returning the normalized event shape above so `state.py`
and `app.py` are unaffected. Events for IPs/hostnames absent from `users.json`
are silently ignored when read from files (the manual API returns 400 instead).
