# Digi Access Scoreboard

A small FastAPI application for live classroom demos. It reads Digi WebUI,
RADIUS, and TACACS+ authentication logs, maps router IPs to participants, and
pushes scoreboard updates to the browser over WebSocket.

## Requirements

- Python 3.10 or newer
- `fastapi`
- `uvicorn`

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure participants

Edit `users.json`. Each router IP must be unique:

```json
{
  "participants": [
    {
      "name": "Javi",
      "router_ip": "10.10.65.72",
      "display_name": "Javi",
      "syslog_host": "00409DDE26B5"
    }
  ]
}
```

`router_ip` is the NAS/router IP found in TACACS+ accounting. `syslog_host`
is the Digi hostname or MAC found immediately after the timestamp in syslog.
It is required when the WebUI syslog message does not contain the router IP.
The `remote=` value is the client workstation and must not be used as the
participant router IP.

Restart the application after changing this file.

## Configure scoring

Edit `scoring.json`:

```json
{
  "points_per_service_per_minute": 10,
  "service_timeout_seconds": 300,
  "score_interval_seconds": 60,
  "services": ["webui", "radius", "tacacs"]
}
```

At every scoring interval, each active green service awards
`points_per_service_per_minute` points. A green service turns red when it has
not received a refresh event within `service_timeout_seconds`.

Restart the application after changing scoring settings.

## Run demo mode

Demo mode is the default. It reads `sample_logs.txt`, waits a random 1–3
seconds between lines, and loops:

```bash
python app.py
```

Then open <http://localhost:8000>.

To play the file once:

```bash
DEMO_LOOP=false python app.py
```

To use another sample file:

```bash
LOG_MODE=demo LOG_FILE=/path/to/sample.log python app.py
```

## Run live mode

Live mode follows these two files simultaneously by default:

```bash
LOG_MODE=live python app.py
```

- `/var/log/syslog` for Digi WebUI `web`, `https`, or `webui` events
- `/var/log/tac_plus_acct.log` for TACACS+ and RADIUS SSH accounting

In `tac_plus_acct.log`, `admintac` is classified as TACACS+ and
`adminradius` is classified as RADIUS. `start` turns the service green and
`stop` turns it red. The first IP after the timestamp is treated as the router
IP; the later IP is the remote client.

The SSH/PAM copies in syslog are intentionally ignored to prevent duplicate
TACACS+ events.

To select different or additional files, use a comma-separated list:

```bash
LOG_MODE=live \
LIVE_LOG_FILES=/var/log/syslog,/var/log/tac_plus_acct.log \
python app.py
```

The older single-file setting remains supported:

```bash
LOG_MODE=live LOG_FILE=/var/log/digi-demo.log python app.py
```

Files are opened at their end by default. To process existing lines first:

```bash
LOG_MODE=live LIVE_FROM_START=true python app.py
```

The application handles truncation/log rotation and retries every two seconds
if a file does not exist or cannot be read. The operating-system user running
the application must have permission to read each selected file.

FreeRADIUS detail accounting files are not required for this setup because
the router also writes both `admintac` and `adminradius` sessions to
`tac_plus_acct.log`. Avoid reading the detail files at the same time unless
you specifically want duplicate accounting sources.

To run without either log reader:

```bash
LOG_MODE=off python app.py
```

## Manual event testing

Post a normalized event:

```bash
curl -X POST http://localhost:8000/api/event \
  -H "Content-Type: application/json" \
  -d '{"participant_ip":"10.10.65.72","service":"webui","status":"green","event_type":"login_success","username":"admin","raw":"manual test"}'
```

Other endpoints:

```bash
curl http://localhost:8000/api/state
curl -X POST http://localhost:8000/api/reset
```

The WebSocket endpoint is `ws://localhost:8000/ws`.

## Optional state persistence

The default state is in memory and resets when the process restarts. To persist
scores, statuses, and recent events to JSON:

```bash
STATE_FILE=scoreboard-state.json python app.py
```

Do not use `users.json` as the state file.

## Adapting parsers to real logs

Parser functions and regular expressions are in `parsers.py`:

- `parse_digi_webui(line)`
- `parse_aaa_accounting(line)`
- `parse_radius(line)`
- `parse_tacacs(line)`
- `parse_log_line(line)`

When real device logs are available, adjust the regex patterns inside the
service-specific parser. Each parser should continue returning this normalized
shape:

```json
{
  "participant_ip": "10.10.65.72",
  "service": "webui",
  "status": "green",
  "event_type": "login_success",
  "username": "admin",
  "raw": "original log line"
}
```

Events for IP addresses not present in `users.json` are ignored when read from
a log file. The manual API returns HTTP 400 for unknown IPs or invalid values.
