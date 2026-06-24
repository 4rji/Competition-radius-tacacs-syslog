# Digi Access Scoreboard

A small FastAPI application for live classroom demos. It detects SYSLOG,
RADIUS, and TACACS+ traffic, maps router IPs to participants, and
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
      "router_ip": "10.10.65.72"
    }
  ]
}
```

`router_ip` is the router source IP found in SYSLOG packet captures and the NAS
IP found in TACACS+ accounting. `syslog_host` is the 12-character Digi
identifier found immediately after the timestamp in stored syslog lines. The
dashboard displays the value from `name`; there is no separate display-name
field to maintain.

Restart the application after changing this file.

## Configure scoring

Edit `scoring.json`:

```json
{
  "points_per_service_first_login": 10,
  "one_time_points": 10,
  "one_time_services": ["syslog"],
  "services": ["syslog", "radius", "tacacs"]
}
```

The first valid SYSLOG packet gives the participant `one_time_points` once.
SYSLOG stays Active and never times out; additional packets do not add points.
The first successful RADIUS login and the first successful TACACS+ login each
award `points_per_service_first_login` immediately. Logout does not remove
points: the service changes from Active to Logged to show that its challenge
was completed. Later logins do not award duplicate points.

Participants who complete all three services and reach 30 points are listed in
the Scoring card. The Winner button cycles through every qualified participant
with a raffle-style reel and randomly selects one winner. The final view shows
only the winner's name. At least two qualified participants are required to
start a draw.

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

- `/var/log/syslog` for stored Digi messages identified by timestamp and
  12-character Digi hostname
- `/var/log/tac_plus_acct.log` for TACACS+ and RADIUS SSH accounting

The SYSLOG parser accepts stored Digi lines:

```text
2026-06-24T16:13:19-05:00 0027044166EF user User admin POST page login from IP 10.10.61.76 via port 443
```

The `10.10.61.76` address is the browser/client and is not used to identify the
participant. The participant is matched using `0027044166EF` and its
`syslog_host` entry in `users.json`.

Captured UDP/514 lines are also supported and use the source IP before the
source port:

```text
10:55:08.117927 enp0s3 In IP 10.10.65.72.47973 > 10.10.65.214.514: SYSLOG local0.notice, length: 92
```

In this example, `10.10.65.72` receives 10 points the first time the line is
detected. It is not marked disconnected later.

In `tac_plus_acct.log`, `admintac` is classified as TACACS+ and
`adminradius` is classified as RADIUS. `start` turns the service green and
`stop` turns it red. The first IP after the timestamp is treated as the router
IP; the later IP is the remote client.

The SSH/PAM copies in syslog are intentionally ignored to prevent duplicate
TACACS+ events.

Stored Digi SYSLOG lines also recognize web sessions for the `adminradius`
user. A `successfully opened web session` message turns RADIUS green and a
`logout web session` message turns it red. The participant is matched through
the 12-character Digi hostname and its `syslog_host` entry in `users.json`.
Existing RADIUS SSH accounting and native FreeRADIUS parsing continue to work
unchanged.

The same stored Digi web-session messages are recognized for `admintac`:
opening a session turns TACACS+ Active and logout changes it to Logged. Existing
TACACS+ SSH accounting remains unchanged.

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
  -d '{"participant_ip":"10.10.65.72","service":"syslog","status":"green","event_type":"syslog_received","raw":"manual test"}'
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

- `parse_syslog(line)`
- `parse_digi_radius_session(line)`
- `parse_digi_tacacs_session(line)`
- `parse_aaa_accounting(line)`
- `parse_radius(line)`
- `parse_tacacs(line)`
- `parse_log_line(line)`
- `parse_log_events(line)`

When real device logs are available, adjust the regex patterns inside the
service-specific parser. Each parser should continue returning this normalized
shape:

```json
{
  "participant_ip": "10.10.65.72",
  "service": "syslog",
  "status": "green",
  "event_type": "syslog_received",
  "username": null,
  "raw": "original log line"
}
```

Events for IP addresses not present in `users.json` are ignored when read from
a log file. The manual API returns HTTP 400 for unknown IPs or invalid values.
